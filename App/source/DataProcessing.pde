
//------------------------------------------------------------------------
//                       Global Variables & Instances
//------------------------------------------------------------------------
import ddf.minim.analysis.*; //for FFT

import brainflow.DataFilter;
import brainflow.FilterTypes;

String curTimestamp;
HashMap<Integer,String> index_of_times;

float playback_speed_fac = 1.0f;  //make 1.0 for real-time.  larger for faster playback

//------------------------------------------------------------------------
//                       Global Functions
//------------------------------------------------------------------------


void processNewData() {

    List<double[]> currentData = currentBoard.getData(getCurrentBoardBufferSize());
    int[] exgChannels = currentBoard.getEXGChannels();
    int channelCount = currentBoard.getNumEXGChannels();
    int bufferSize = dataProcessingRawBuffer[0].length;

    // Read each row once. This is especially important for the circular history
    // buffer, and avoids doing one synchronized list lookup per channel.
    for (int i = 0; i < bufferSize; i++) {
        double[] row = currentData.get(i);
        for (int Ichan = 0; Ichan < channelCount; Ichan++) {
            dataProcessingRawBuffer[Ichan][i] = (float)row[exgChannels[Ichan]];
        }
    }
    for (int Ichan = 0; Ichan < channelCount; Ichan++) {
        System.arraycopy(dataProcessingRawBuffer[Ichan], 0,
                         dataProcessingFilteredBuffer[Ichan], 0, bufferSize);
    }

    //apply additional processing for the time-domain montage plot (ie, filtering)
    dataProcessing.process(dataProcessingFilteredBuffer, fftBuff);

    dataProcessing.newDataToSend = true;
    dataProcessingGeneration++;

    //look to see if the latest data is railed so that we can notify the user on the GUI
    for (int Ichan=0; Ichan < nchan; Ichan++) is_railed[Ichan].update(dataProcessingRawBuffer[Ichan], Ichan);

    //compute the electrode impedance. Do it in a very simple way [rms to amplitude, then uVolt to Volt, then Volt/Amp to Ohm]
    for (int Ichan=0; Ichan < nchan; Ichan++) {
        // Calculate the impedance
        float impedance = (sqrt(2.0)*dataProcessing.data_std_uV[Ichan]*1.0e-6) / BoardCytonConstants.leadOffDrive_amps;
        // Subtract the 2.2kOhm resistor
        impedance -= BoardCytonConstants.series_resistor_ohms;
        // Verify the impedance is not less than 0
        if (impedance < 0) {
            // Incase impedance some how dipped below 2.2kOhm
            impedance = 0;
        }
        // Store to the global variable
        data_elec_imp_ohm[Ichan] = impedance;
    }
}

// Only the visible Time Series duration needs a fully filtered history. Two
// preceding seconds are retained as filter warm-up, matching dataBuff_len_sec.
int getDataProcessingSampleCount() {
    int visibleSeconds = 5;
    if (w_timeSeries != null && w_timeSeries.getTSHorizScale() != null) {
        visibleSeconds = w_timeSeries.getTSHorizScale().getValue();
    }
    int samples = (visibleSeconds + 2) * currentBoard.getSampleRate();
    samples = max(samples, getNfftSafe());
    return min(samples, getCurrentBoardBufferSize());
}

void initializeFFTObjects(ddf.minim.analysis.FFT[] fftBuff, float[][] dataProcessingRawBuffer, int Nfft, float fs_Hz) {

    float[] fooData;
    for (int Ichan=0; Ichan < nchan; Ichan++) {
        //make the FFT objects...Following "SoundSpectrum" example that came with the Minim library
        fftBuff[Ichan].window(ddf.minim.analysis.FFT.HAMMING);

        //do the FFT on the initial data
        if (isFFTFiltered == true) {
            fooData = dataProcessingFilteredBuffer[Ichan];  //use the filtered data for the FFT
        } else {
            fooData = dataProcessingRawBuffer[Ichan];  //use the raw data for the FFT
        }
        fooData = Arrays.copyOfRange(fooData, fooData.length-Nfft, fooData.length);
        fftBuff[Ichan].forward(fooData); //compute FFT on this channel of data
    }
}

//------------------------------------------------------------------------
//                          CLASSES
//------------------------------------------------------------------------

class DataProcessing {
    private float fs_Hz;  //sample rate
    private int nchan;
    float data_std_uV[];
    float polarity[];
    boolean newDataToSend;
    final int[] processing_band_low_Hz = {
        1, 4, 8, 13, 30
    }; //lower bound for each frequency band of interest (2D classifier only)
    final int[] processing_band_high_Hz = {
        4, 8, 13, 30, 55
    };  //upper bound for each frequency band of interest
    float avgPowerInBins[][];
    float headWidePower[];
    private double[][] filterScratch;
    private float[] fftWorkBuffer;
    private float[] prevFFTdata;

    public EmgSettings emgSettings;

    DataProcessing(int NCHAN, float sample_rate_Hz) {
        nchan = NCHAN;
        fs_Hz = sample_rate_Hz;
        data_std_uV = new float[nchan];
        polarity = new float[nchan];
        newDataToSend = false;
        avgPowerInBins = new float[nchan][processing_band_low_Hz.length];
        headWidePower = new float[processing_band_low_Hz.length];
        filterScratch = new double[nchan][];
        fftWorkBuffer = new float[getNfftSafe()];
        prevFFTdata = new float[getNfftSafe()/2 + 1];

        emgSettings = new EmgSettings();
    }
    
    //Process data on a channel-by-channel basis
    private synchronized void processChannel(int Ichan, float[][] data_forDisplay_uV, float[] prevFFTdata) {            
        int Nfft = getNfftSafe();
        double foo;

        // Filter the data in the time domain
        // TODO: Use double arrays here and convert to float only to plot data.
        // ^^^ This might not feasible or meaningful performance improvement. I looked into it a while ago and it seems we need floats for the FFT library also. -RW 2022)
        try {
            int samplesToFilter = min(getDataProcessingSampleCount(), data_forDisplay_uV[Ichan].length);
            int filterStart = data_forDisplay_uV[Ichan].length - samplesToFilter;
            if (filterScratch[Ichan] == null || filterScratch[Ichan].length != samplesToFilter) {
                filterScratch[Ichan] = new double[samplesToFilter];
            }
            double[] tempArray = filterScratch[Ichan];
            for (int i = 0; i < samplesToFilter; i++) {
                tempArray[i] = data_forDisplay_uV[Ichan][filterStart + i];
            }
            
            //Apply BandStop filter if the filter should be active on this channel
            if (filterSettings.values.bandStopFilterActive[Ichan].isActive()) {
                DataFilter.perform_bandstop(
                    tempArray,
                    currentBoard.getSampleRate(),
                    filterSettings.values.bandStopStartFreq[Ichan],
                    filterSettings.values.bandStopStopFreq[Ichan],
                    filterSettings.values.bandStopFilterOrder[Ichan].getValue(),
                    filterSettings.values.bandStopFilterType[Ichan].getValue(),
                    1.0);
            }

            //Apply BandPass filter if the filter should be active on this channel
            if (filterSettings.values.bandPassFilterActive[Ichan].isActive()) {
                DataFilter.perform_bandpass(
                    tempArray,
                    currentBoard.getSampleRate(),
                    filterSettings.values.bandPassStartFreq[Ichan],
                    filterSettings.values.bandPassStopFreq[Ichan],
                    filterSettings.values.bandPassFilterOrder[Ichan].getValue(),
                    filterSettings.values.bandPassFilterType[Ichan].getValue(),
                    1.0);
            }

            //Apply Environmental Noise filter on all channels. Do it like this since there are no codes for NONE or FIFTY_AND_SIXTY in BrainFlow
            switch (filterSettings.values.globalEnvFilter) {
                case FIFTY_AND_SIXTY:
                    DataFilter.remove_environmental_noise(
                        tempArray,
                        currentBoard.getSampleRate(),
                        NoiseTypes.FIFTY.get_code());
                    DataFilter.remove_environmental_noise(
                        tempArray,
                        currentBoard.getSampleRate(),
                        NoiseTypes.SIXTY.get_code());
                    break;
                case FIFTY:
                    DataFilter.remove_environmental_noise(
                        tempArray,
                        currentBoard.getSampleRate(),
                        NoiseTypes.FIFTY.get_code());
                    break;
                case SIXTY:
                    DataFilter.remove_environmental_noise(
                        tempArray,
                        currentBoard.getSampleRate(),
                        NoiseTypes.SIXTY.get_code());
                    break;
                default:
                    break;
            }

            for (int i = 0; i < samplesToFilter; i++) {
                data_forDisplay_uV[Ichan][filterStart + i] = (float)tempArray[i];
            }
        } catch (BrainFlowError e) {
            e.printStackTrace();
        }

        //compute the standard deviation of the filtered signal...this is for the head plot
        data_std_uV[Ichan] = stdTail(dataProcessingFilteredBuffer[Ichan], (int)fs_Hz);

        //copy the previous FFT data...enables us to apply some smoothing to the FFT data
        for (int I=0; I < fftBuff[Ichan].specSize(); I++) {
            prevFFTdata[I] = fftBuff[Ichan].getBand(I); //copy the old spectrum values
        }

        //prepare the data for the new FFT
        float[] sourceData;
        if (isFFTFiltered == true) {
            sourceData = dataProcessingFilteredBuffer[Ichan];  //use the filtered data for the FFT
        } else {
            sourceData = dataProcessingRawBuffer[Ichan];  //use the raw data for the FFT
        }
        int fftStart = sourceData.length - Nfft;
        float meanData = 0;
        for (int I = 0; I < Nfft; I++) {
            fftWorkBuffer[I] = sourceData[fftStart + I];
            meanData += fftWorkBuffer[I];
        }
        meanData /= Nfft;
        for (int I = 0; I < Nfft; I++) fftWorkBuffer[I] -= meanData;

        //compute the FFT
        fftBuff[Ichan].forward(fftWorkBuffer); //compute FFT on this channel of data

        // FFT ref: https://www.mathworks.com/help/matlab/ref/fft.html
        // first calculate double-sided FFT amplitude spectrum
        for (int I=0; I <= Nfft/2; I++) {
            fftBuff[Ichan].setBand(I, (float)(fftBuff[Ichan].getBand(I) / Nfft));
        }
        // then convert into single-sided FFT spectrum: DC & Nyquist (i=0 & i=N/2) remain the same, others multiply by two.
        for (int I=1; I < Nfft/2; I++) {
            fftBuff[Ichan].setBand(I, (float)(fftBuff[Ichan].getBand(I) * 2));
        }

        //average the FFT with previous FFT data so that it makes it smoother in time
        double min_val = 0.01d;
        for (int I=0; I < fftBuff[Ichan].specSize(); I++) {   //loop over each fft bin
            if (prevFFTdata[I] < min_val) prevFFTdata[I] = (float)min_val; //make sure we're not too small for the log calls
            foo = fftBuff[Ichan].getBand(I);
            if (foo < min_val) foo = min_val; //make sure this value isn't too small

            if (true) {
                //smooth in dB power space
                foo =   (1.0d-smoothFac[smoothFac_ind]) * java.lang.Math.log(java.lang.Math.pow(foo, 2));
                foo += smoothFac[smoothFac_ind] * java.lang.Math.log(java.lang.Math.pow((double)prevFFTdata[I], 2));
                foo = java.lang.Math.sqrt(java.lang.Math.exp(foo)); //average in dB space
            } else {
                //smooth (average) in linear power space
                foo =   (1.0d-smoothFac[smoothFac_ind]) * java.lang.Math.pow(foo, 2);
                foo+= smoothFac[smoothFac_ind] * java.lang.Math.pow((double)prevFFTdata[I], 2);
                // take sqrt to be back into uV_rtHz
                foo = java.lang.Math.sqrt(foo);
            }
            fftBuff[Ichan].setBand(I, (float)foo); //put the smoothed data back into the fftBuff data holder for use by everyone else
            // fftBuff[Ichan].setBand(I, 1.0f);  // test
        } //end loop over FFT bins

        // calculate single-sided psd by single-sided FFT amplitude spectrum
        // PSD ref: https://www.mathworks.com/help/dsp/ug/estimate-the-power-spectral-density-in-matlab.html
        // when i = 1 ~ (N/2-1), psd = (N / fs) * mag(i)^2 / 4
        // when i = 0 or i = N/2, psd = (N / fs) * mag(i)^2

        Arrays.fill(avgPowerInBins[Ichan], 0);
        for (int Ibin = 0; Ibin <= Nfft/2; Ibin++) {
            float FFT_freq_Hz = fftBuff[Ichan].indexToFreq(Ibin);
            if (FFT_freq_Hz >= processing_band_high_Hz[processing_band_high_Hz.length - 1]) {
                break;
            }
            for (int band = 0; band < processing_band_low_Hz.length; band++) {
                if (FFT_freq_Hz >= processing_band_low_Hz[band] && FFT_freq_Hz < processing_band_high_Hz[band]) {
                    float amplitude = fftBuff[Ichan].getBand(Ibin);
                    float psdx = amplitude * amplitude * Nfft / currentBoard.getSampleRate();
                    if (Ibin != 0 && Ibin != Nfft/2) {
                        psdx /= 4;
                    }
                    avgPowerInBins[Ichan][band] += psdx;
                    break;
                }
            }
        }
    }

    public void process(float[][] data_forDisplay_uV, ddf.minim.analysis.FFT[] fftData) {              //holds the FFT (frequency spectrum) of the latest data

        for (int Ichan=0; Ichan < nchan; Ichan++) { 
            processChannel(Ichan, data_forDisplay_uV, prevFFTdata);
        } //end the loop over channels.

        for (int i = 0; i < processing_band_low_Hz.length; i++) {
            float sum = 0;

            for (int j = 0; j < nchan; j++) {
                sum += avgPowerInBins[j][i];
            }
            headWidePower[i] = sum/nchan;   // averaging power over all channels
        }

        //find strongest channel
        int refChanInd = findMax(data_std_uV);
        //println("EEG_Processing: strongest chan (one referenced) = " + (refChanInd+1));
        //compute polarity of each channel
        float[] refData_uV = dataProcessingFilteredBuffer[refChanInd];
        for (int Ichan=0; Ichan < nchan; Ichan++) {
            float dotProd = calcDotProductTail(dataProcessingFilteredBuffer[Ichan], refData_uV, (int)fs_Hz);
            if (dotProd >= 0.0f) {
                polarity[Ichan]=1.0;
            } else {
                polarity[Ichan]=-1.0;
            }
        }

        //Compute EMG values independent of widgets
        emgSettings.values.process(dataProcessingFilteredBuffer);
    }

    private float stdTail(float[] data, int count) {
        int samples = min(count, data.length);
        int start = data.length - samples;
        float average = 0;
        for (int i = start; i < data.length; i++) average += data[i];
        average /= samples;

        float variance = 0;
        for (int i = start; i < data.length; i++) {
            float delta = data[i] - average;
            variance += delta * delta;
        }
        return (float)Math.sqrt(variance / samples);
    }

    private float calcDotProductTail(float[] data1, float[] data2, int count) {
        int samples = min(count, min(data1.length, data2.length));
        int start1 = data1.length - samples;
        int start2 = data2.length - samples;
        float value = 0;
        for (int i = 0; i < samples; i++) {
            value += data1[start1 + i] * data2[start2 + i];
        }
        return value;
    }
}
