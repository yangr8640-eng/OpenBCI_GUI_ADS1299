
//////////////////////////////////////////////////////
//                                                  //
//                  W_Spectrogram.pde               //
//                                                  //
//                                                  //
//    Created by: Richard Waltman, September 2019   //
//                                                  //
//////////////////////////////////////////////////////

class W_Spectrogram extends Widget {

    //to see all core variables/methods of the Widget class, refer to Widget.pde
    public ChannelSelect spectChanSelectTop;
    public ChannelSelect spectChanSelectBot;
    private boolean chanSelectWasOpen = false;
    List<controlP5.Controller> cp5ElementsToCheck = new ArrayList<controlP5.Controller>();

    int xPos = 0;
    int hueLimit = 160;

    PImage dataImg;
    int dataImageW = 1800;
    int dataImageH = 200;
    int prevW = 0;
    int prevH = 0;
    float scaledWidth;
    float scaledHeight;
    int graphX = 0;
    int graphY = 0;
    int graphW = 0;
    int graphH = 0;
    int midLineY = 0;

    private int lastShift = 0;
    private int scrollSpeed = 100; // == 10Hz
    private boolean wasRunning = false;

    int paddingLeft = 54;
    int paddingRight = 26;   
    int paddingTop = 8;
    int paddingBottom = 50;
    int numHorizAxisDivs = 3;
    int numVertAxisDivs = 8;
    final int[][] vertAxisLabels = {
        {20, 15, 10, 5, 0, 5, 10, 15, 20},
        {40, 30, 20, 10, 0, 10, 20, 30, 40},
        {60, 45, 30, 15, 0, 15, 30, 45, 60},
        {100, 75, 50, 25, 0, 25,  50, 75, 100},
        {120, 90, 60, 30, 0, 30, 60, 90, 120},
        {250, 188, 125, 63, 0, 63, 125, 188, 250}
    };
    int[] vertAxisLabel;
    final float[][] horizAxisLabels = {
        {30, 25, 20, 15, 10, 5, 0},
        {6, 5, 4, 3, 2, 1, 0},
        {3, 2, 1, 0},
        {1.5, 1, .5, 0},
        {1, .5, 0}
    };
    float[] horizAxisLabel;
    StringList horizAxisLabelStrings;

    float[] topFFTAvg;
    float[] botFFTAvg;

    // Enhanced spectrogram processing
    private MelFilterBank melFilterBank;
    private int nMelBands = 64;
    private int currentColormap = 0;       // 0=Inferno, 1=Jet, 2=Viridis, 3=BlueGreen
    private boolean useMelScale = false;   // false=Linear, true=Mel
    private color[] colormapLUT;
    private float[][] cachedSpectra;       // [nchan][specSize] — cached per-channel FFT amplitudes
    private float[] workBuffer;            // reused float buffer for FFT input
    private float dBMin = -40.0f;
    private float dBMax = 0.0f;

    W_Spectrogram(PApplet _parent){
        super(_parent); //calls the parent CONSTRUCTOR method of Widget (DON'T REMOVE)

        //Add channel select dropdown to this widget
        spectChanSelectTop = new ChannelSelect(pApplet, this, x, y, w, navH, "Spectrogram_Channels_Top");
        spectChanSelectBot = new ChannelSelect(pApplet, this, x, y + navH, w, navH, "Spectrogram_Channels_Bot");
        activateDefaultChannels();
        spectChanSelectTop.setIsDualChannelSelect(true);
        spectChanSelectBot.setIsDualChannelSelect(true);
        spectChanSelectBot.setIsFirstRowChannelSelect(false);
        cp5ElementsToCheck.addAll(spectChanSelectTop.getCp5ElementsForOverlapCheck());
        cp5ElementsToCheck.addAll(spectChanSelectBot.getCp5ElementsForOverlapCheck());

        xPos = w - 1; //draw on the right, and shift pixels to the left
        prevW = w;
        prevH = h;
        graphX = x + paddingLeft;
        graphY = y + paddingTop;
        graphW = w - paddingRight - paddingLeft;
        graphH = h - paddingBottom - paddingTop;

        settings.spectMaxFrqSave = 1;
        settings.spectSampleRateSave = 2;
        settings.spectFreqScaleSave = 0;
        settings.spectColormapSave = 0;
        vertAxisLabel = vertAxisLabels[settings.spectMaxFrqSave];
        horizAxisLabel = horizAxisLabels[settings.spectSampleRateSave];
        horizAxisLabelStrings = new StringList();
        //Fetch/calculate the time strings for the horizontal axis ticks
        fetchTimeStrings(numHorizAxisDivs);

        //This is the protocol for setting up dropdowns.
        //Note that these dropdowns correspond to the global callback functions of the same name
        addDropdown("SpectrogramMaxFreq", "Max Freq", Arrays.asList(settings.spectMaxFrqArray), settings.spectMaxFrqSave);
        addDropdown("SpectrogramSampleRate", "Window", Arrays.asList(settings.spectSampleRateArray), settings.spectSampleRateSave);
        addDropdown("SpectrogramFreqScale", "Freq Scale", Arrays.asList("Linear", "Mel"), settings.spectFreqScaleSave);
        addDropdown("SpectrogramColormap", "Colormap", Arrays.asList("Inferno", "Jet", "Viridis", "BlueGreen"), settings.spectColormapSave);

        //Initialize the colormap lookup table
        currentColormap = settings.spectColormapSave;
        colormapLUT = getColormapLUT(currentColormap);

        //Resize the height of the data image using default
        dataImageH = vertAxisLabel[0] * 2;
        //Create image using correct dimensions! Fixes bug where image size and labels do not align on session start.
        dataImg = createImage(dataImageW, dataImageH, RGB);

        //Build the mel filterbank for the default FFT configuration
        buildMelFilterBank();
    }

    void update(){
        super.update(); //calls the parent update() method of Widget (DON'T REMOVE)

        //Update channel checkboxes and active channels
        spectChanSelectTop.update(x, y, w);
        spectChanSelectBot.update(x, y + navH, w);
        //Let the top channel select open the bottom one also so we can open both with 1 button
        if (chanSelectWasOpen != spectChanSelectTop.isVisible()) {
            spectChanSelectBot.setIsVisible(spectChanSelectTop.isVisible());
            chanSelectWasOpen = spectChanSelectTop.isVisible();
            //Allow spectrogram to flex size and position depending on if the channel select is open
            flexSpectrogramSizeAndPosition();
        }

        if (spectChanSelectTop.isVisible()) {
            lockElementsOnOverlapCheck(cp5ElementsToCheck);
        }
        
        if (currentBoard.isStreaming()) {
            //Make sure we are always draw new pixels on the right
            xPos = dataImg.width - 1;
            //Fetch/calculate the time strings for the horizontal axis ticks
            fetchTimeStrings(numHorizAxisDivs);
            //Compute unsmoothed FFT for all active channels (cached for draw)
            computeUnsmooothedSpectra();
        }
        
        //State change check
        if (currentBoard.isStreaming() && !wasRunning) {
            onStartRunning();
        } else if (!currentBoard.isStreaming() && wasRunning) {
            onStopRunning();
        }
    }

    private void onStartRunning() {
        wasRunning = true;
        lastShift = millis();
        // Rebuild mel filterbank (sample rate may have changed)
        buildMelFilterBank();
        // Initialize cached spectra array
        int specSize = fftBuff[0].specSize();
        cachedSpectra = new float[nchan][specSize];
        workBuffer = new float[getNfftSafe()];
    }

    private void onStopRunning() {
        wasRunning = false;
    }

    public void draw(){
        super.draw(); //calls the parent draw() method of Widget (DON'T REMOVE)

        //put your code here... //remember to refer to x,y,w,h which are the positioning variables of the Widget class
        
        //Scale the dataImage to fit in inside the widget
        float scaleW = float(graphW) / dataImageW;
        float scaleH = float(graphH) / dataImageH;

        pushStyle();
        fill(0);
        rect(x, y, w, h); //draw a black background for the widget
        popStyle();

        //draw the spectrogram if the widget is open, and update pixels if board is streaming data
        if (currentBoard.isStreaming()) {
            pushStyle();
            dataImg.loadPixels();

            //Shift all pixels to the left! (every scrollspeed ms)
            if(millis() - lastShift > scrollSpeed) {
                for (int r = 0; r < dataImg.height; r++) {
                    if (r != 0) {
                        arrayCopy(dataImg.pixels, dataImg.width * r, dataImg.pixels, dataImg.width * r - 1, dataImg.width);
                    } else {
                        //When there would be an ArrayOutOfBoundsException, account for it!
                        arrayCopy(dataImg.pixels, dataImg.width * (r + 1), dataImg.pixels, r * dataImg.width, dataImg.width);
                    }
                }

                lastShift += scrollSpeed;
            }

            // Render new pixel column for each channel group (top/bottom)
            int numRows = dataImg.height / 2;
            colorMode(RGB, 255, 255, 255);

            // --- TOP channel group ---
            float[] specDataTop = getSpectrogramData(spectChanSelectTop, numRows);
            for (int row = 0; row < numRows; row++) {
                float normVal = (row < specDataTop.length) ? specDataTop[row] : 0.0f;
                int lutIdx = constrain((int)(normVal * (COLORMAP_LUT_SIZE - 1)), 0, COLORMAP_LUT_SIZE - 1);
                int pixelRow = numRows - 1 - row; // flip so low freq at bottom
                int loc = xPos + (pixelRow * dataImg.width);
                if (loc >= dataImg.width * dataImg.height) loc = dataImg.width * dataImg.height - 1;
                try {
                    dataImg.pixels[loc] = colormapLUT[lutIdx];
                } catch (Exception e) {
                    println("Spectrogram Top draw error!");
                }
            }

            // --- BOTTOM channel group ---
            float[] specDataBot = getSpectrogramData(spectChanSelectBot, numRows);
            for (int row = 0; row < numRows; row++) {
                float normVal = (row < specDataBot.length) ? specDataBot[row] : 0.0f;
                int lutIdx = constrain((int)(normVal * (COLORMAP_LUT_SIZE - 1)), 0, COLORMAP_LUT_SIZE - 1);
                int pixelRow = row + numRows;
                int loc = xPos + (pixelRow * dataImg.width);
                if (loc >= dataImg.width * dataImg.height) loc = dataImg.width * dataImg.height - 1;
                try {
                    dataImg.pixels[loc] = colormapLUT[lutIdx];
                } catch (Exception e) {
                    println("Spectrogram Bottom draw error!");
                }
            }

            dataImg.updatePixels();
            popStyle();
        }
        
        pushMatrix();
        translate(graphX, graphY);
        scale(scaleW, scaleH);
        image(dataImg, 0, 0);
        popMatrix();

        spectChanSelectTop.draw();
        spectChanSelectBot.draw();
        drawAxes(scaleW, scaleH);
        drawCenterLine();
    }

    public void screenResized(){
        super.screenResized(); //calls the parent screenResized() method of Widget (DON'T REMOVE)

        spectChanSelectTop.screenResized(pApplet);
        spectChanSelectBot.screenResized(pApplet);  
        graphX = x + paddingLeft;
        graphY = y + paddingTop;
        graphW = w - paddingRight - paddingLeft;
        graphH = h - paddingBottom - paddingTop;
        //Allow spectrogram to flex size and position depending on if the channel select is open
        if (spectChanSelectTop.isVisible()) {
            graphY += navH * 2;
            graphH -= navH * 2;
        }
    }

    void mousePressed(){
        super.mousePressed(); //calls the parent mousePressed() method of Widget (DON'T REMOVE)

        spectChanSelectTop.mousePressed(this.dropdownIsActive); //Calls channel select mousePressed and checks if clicked
        spectChanSelectBot.mousePressed(this.dropdownIsActive);
    }

    void mouseReleased(){
        super.mouseReleased(); //calls the parent mouseReleased() method of Widget (DON'T REMOVE)

    }

    void drawAxes(float scaledW, float scaledH) {
        
        pushStyle();
            fill(255);
            textSize(14);
            //draw horizontal axis label
            text("Time", x + w/2 - textWidth("Time")/3, y + h - 9);
            noFill();
            stroke(255);
            strokeWeight(2);
            //draw rectangle around the spectrogram
            rect(graphX, graphY, scaledW * dataImageW, scaledH * dataImageH);
        popStyle();

        pushStyle();
            //draw horizontal axis ticks from left to right
            int tickMarkSize = 7; //in pixels
            float horizAxisX = graphX;
            float horizAxisY = graphY + scaledH * dataImageH;
            stroke(255);
            fill(255);
            strokeWeight(2);
            textSize(11);
            for (int i = 0; i <= numHorizAxisDivs; i++) {
                float offset = scaledW * dataImageW * (float(i) / numHorizAxisDivs);
                line(horizAxisX + offset, horizAxisY, horizAxisX + offset, horizAxisY + tickMarkSize);
                if (horizAxisLabelStrings.get(i) != null) {
                    text(horizAxisLabelStrings.get(i), horizAxisX + offset - (int)textWidth(horizAxisLabelStrings.get(i))/2, horizAxisY + tickMarkSize * 3);
                }
            }
        popStyle();
        
        pushStyle();
            pushMatrix();
                rotate(radians(-90));
                translate(-h/2 - textWidth("Frequency (Hz)")/3, 20);
                fill(255);
                textSize(14);
                //draw y axis label
                text("Frequency (Hz)", -y, x);
            popMatrix();
        popStyle();

        pushStyle();
            //draw vertical axis ticks from top to bottom
            float vertAxisX = graphX;
            float vertAxisY = graphY;
            stroke(255);
            fill(255);
            textSize(12);
            strokeWeight(2);
            for (int i = 0; i <= numVertAxisDivs; i++) {
                float offset = scaledH * dataImageH * (float(i) / numVertAxisDivs);
                line(vertAxisX, vertAxisY + offset, vertAxisX - tickMarkSize, vertAxisY + offset);
                // Determine label text: mel or linear
                String label;
                if (useMelScale && melFilterBank != null) {
                    // Map position to mel band, then to Hz
                    float frac = (float)i / numVertAxisDivs;
                    int melIdx = round(frac * (nMelBands - 1));
                    float hz = melFilterBank.getMelBandCenterHz(melIdx);
                    label = nf(hz, 0, 1); // 1 decimal place
                } else {
                    label = Integer.toString(vertAxisLabel[i]);
                }
                if (vertAxisLabel[i] == 0) midLineY = int(vertAxisY + offset);
                offset += paddingTop/2;
                text(label, vertAxisX - tickMarkSize*2 - (int)textWidth(label), vertAxisY + offset);
            }
        popStyle();

        drawColorScaleReference();
    }

    void drawCenterLine() {
        //draw a thick line down the middle to separate the two plots
        pushStyle();
        stroke(255);
        strokeWeight(3);
        line(graphX, midLineY, graphX + graphW, midLineY);
        popStyle();
    }

    void drawColorScaleReference() {
        int colorScaleHeight = 128;
        //Dynamically scale the amplitude-to-color reference bar. If it won't fit, don't draw it.
        if (graphH < colorScaleHeight) {
            colorScaleHeight = int(h * 1/2);
            if (colorScaleHeight > graphH) {
                return;
            }
        }
        pushStyle();
            colorMode(RGB, 255, 255, 255);
            //draw color scale reference to the right of the spectrogram
            for (int i = 0; i < colorScaleHeight; i++) {
                float frac = (float)i / (float)(colorScaleHeight - 1);
                int lutIdx = (int)(frac * (COLORMAP_LUT_SIZE - 1));
                lutIdx = constrain(lutIdx, 0, COLORMAP_LUT_SIZE - 1);
                stroke(colormapLUT[lutIdx]);
                strokeWeight(10);
                point(x + w - paddingRight/2 + 1, midLineY + colorScaleHeight/2 - i);
            }
        popStyle();
    }

    void activateDefaultChannels() {
        int[] topChansToActivate;
        int[] botChansToActivate; 
        if (nchan == 4) {
            topChansToActivate = new int[]{0, 2};
            botChansToActivate = new int[]{1, 3};
        } else if (nchan == 8) {
            topChansToActivate = new int[]{0, 2, 4, 6};
            botChansToActivate = new int[]{1, 3, 5, 7};
        } else {
            topChansToActivate = new int[]{0, 2, 4, 6, 8 ,10, 12, 14};
            botChansToActivate = new int[]{1, 3, 5, 7, 9, 11, 13, 15};
        }

        for (int i = 0; i < topChansToActivate.length; i++) {
            spectChanSelectTop.setToggleState(topChansToActivate[i], true);
            
        }

        for (int i = 0; i < botChansToActivate.length; i++) {
            spectChanSelectBot.setToggleState(botChansToActivate[i], true);
        }
    }

    void flexSpectrogramSizeAndPosition() {
        if (spectChanSelectTop.isVisible()) {
            graphY += navH * 2;
            graphH -= navH * 2;
        } else {
            graphY -= navH * 2;
            graphH += navH * 2;
        }
    }

    void setScrollSpeed(int i) {
        scrollSpeed = i;
    }

    // ============ Enhanced Spectrogram Processing Methods ============

    /**
     * Compute unsmoothed FFT for all channels in a given channel group.
     * Uses fftBuffSpectrogram[] which is never smoothed by DataProcessing.
     * Results cached in cachedSpectra[][] for use by getSpectrogramData().
     */
    private void computeUnsmooothedSpectra() {
        int nfft = getNfftSafe();
        if (workBuffer == null || workBuffer.length != nfft) {
            workBuffer = new float[nfft];
        }

        // Gather all active channels from both groups
        java.util.Set<Integer> allActiveChans = new java.util.HashSet<Integer>();
        for (int i : spectChanSelectTop.activeChan) allActiveChans.add(i);
        for (int i : spectChanSelectBot.activeChan) allActiveChans.add(i);

        for (int chan : allActiveChans) {
            // Extract last Nfft samples from filtered buffer
            float[] chanData = dataProcessingFilteredBuffer[chan];
            int dataLen = chanData.length;
            for (int j = 0; j < nfft; j++) {
                workBuffer[j] = chanData[dataLen - nfft + j];
            }
            // Remove DC mean
            float mean = 0.0f;
            for (int j = 0; j < nfft; j++) mean += workBuffer[j];
            mean /= nfft;
            for (int j = 0; j < nfft; j++) workBuffer[j] -= mean;

            // Forward FFT (unsmoothed)
            fftBuffSpectrogram[chan].forward(workBuffer);

            // Read amplitude spectrum (single-sided, normalized)
            int specSize = fftBuffSpectrogram[chan].specSize();
            if (cachedSpectra == null || cachedSpectra.length <= chan || cachedSpectra[chan].length != specSize) {
                if (cachedSpectra == null) cachedSpectra = new float[nchan][specSize];
                else cachedSpectra[chan] = new float[specSize];
            }
            for (int b = 0; b < specSize; b++) {
                float amp = fftBuffSpectrogram[chan].getBand(b) / nfft;
                if (b > 0 && b < specSize - 1) amp *= 2.0f;
                cachedSpectra[chan][b] = amp;
            }
        }
    }

    /**
     * Compute spectrogram data (dB-normalized, 0-1 mapped) for a channel group.
     * Returns float[numRows] where each value is the normalized [0,1] power
     * for that display row.
     */
    private float[] getSpectrogramData(ChannelSelect sel, int numRows) {
        float[] result = new float[numRows];
        if (sel.activeChan.size() == 0) return result;

        int specSize = fftBuff[0].specSize();

        // Average amplitude spectrum across active channels
        float[] avgAmp = new float[specSize];
        for (int chan : sel.activeChan) {
            if (cachedSpectra == null || cachedSpectra.length <= chan) continue;
            for (int b = 0; b < specSize; b++) {
                avgAmp[b] += cachedSpectra[chan][b];
            }
        }
        for (int b = 0; b < specSize; b++) {
            avgAmp[b] /= sel.activeChan.size();
        }

        // Apply mel filterbank if in mel mode
        float[] displayData;
        int displayLen;
        if (useMelScale && melFilterBank != null) {
            displayData = melFilterBank.apply(avgAmp);
            displayLen = min(nMelBands, numRows);
        } else {
            displayData = avgAmp;
            displayLen = min(specSize, numRows);
        }

        // Convert to dB power and normalize to [0, 1]
        // Find max for dB reference
        float maxAmp = 1e-10f;
        for (int i = 0; i < displayLen; i++) {
            if (displayData[i] > maxAmp) maxAmp = displayData[i];
        }
        for (int i = 0; i < displayLen; i++) {
            float val = max(displayData[i], 1e-10f);
            float dbVal = 10.0f * (float)Math.log10(val) - 10.0f * (float)Math.log10(maxAmp);
            result[i] = constrain((dbVal - dBMin) / (dBMax - dBMin), 0.0f, 1.0f);
        }

        return result;
    }

    /**
     * Build or rebuild the mel filterbank based on current FFT and display settings.
     */
    private void buildMelFilterBank() {
        try {
            int nfft = getNfftSafe();
            float sr = currentBoard.getSampleRate();
            if (sr <= 0) return;
            float fMax = vertAxisLabel[0]; // max frequency from current dropdown setting
            int specSize = nfft / 2 + 1;
            melFilterBank = new MelFilterBank(specSize, nMelBands, sr, 0.5f, fMax);
        } catch (Exception e) {
            // Silently handle — mel filterbank will be built later when
            // FFT objects are fully initialized
        }
    }

    void fetchTimeStrings(int numAxisTicks) {
        horizAxisLabelStrings.clear();
        LocalDateTime time;
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("HH:mm:ss");

        if (getCurrentTimeStamp() == 0) {
            time = LocalDateTime.now();
        } else {
            time = LocalDateTime.ofInstant(Instant.ofEpochMilli(getCurrentTimeStamp()), 
                                            TimeZone.getDefault().toZoneId()); 
        }
        
        for (int i = 0; i <= numAxisTicks; i++) {
            long l = (long)(horizAxisLabel[i] * 60f);
            LocalDateTime t = time.minus(l, ChronoUnit.SECONDS);
            horizAxisLabelStrings.append(t.format(formatter));
        }
    }

    //Identical to the method in TimeSeries, but allows spectrogram to get the data directly from the playback data in the background
    //Find times to display for playback position
    private long getCurrentTimeStamp() {
        //return current playback time
        List<double[]> currentData = currentBoard.getData(1);
        int timeStampChan = currentBoard.getTimestampChannel();
        long timestampMS = (long)(currentData.get(0)[timeStampChan] * 1000.0);
        return timestampMS;
    }
};

//These functions need to be global! These functions are activated when an item from the corresponding dropdown is selected
//triggered when there is an event in the Spectrogram Widget MaxFreq. Dropdown
void SpectrogramMaxFreq(int n) {
    settings.spectMaxFrqSave = n;
    //reset the vertical axis labels
    w_spectrogram.vertAxisLabel = w_spectrogram.vertAxisLabels[n];
    //Resize the height of the data image (linear or mel)
    if (w_spectrogram.useMelScale) {
        w_spectrogram.dataImageH = w_spectrogram.nMelBands * 2;
    } else {
        w_spectrogram.dataImageH = w_spectrogram.vertAxisLabel[0] * 2;
    }
    //overwrite the existing image because the sample rate is about to change
    w_spectrogram.dataImg = createImage(w_spectrogram.dataImageW, w_spectrogram.dataImageH, RGB);
    w_spectrogram.buildMelFilterBank();
}

void SpectrogramSampleRate(int n) {
    settings.spectSampleRateSave = n;
    //overwrite the existing image because the sample rate is about to change
    w_spectrogram.dataImg = createImage(w_spectrogram.dataImageW, w_spectrogram.dataImageH, RGB);
    w_spectrogram.horizAxisLabel = w_spectrogram.horizAxisLabels[n];
    if (n == 0) {
        w_spectrogram.numHorizAxisDivs = 6;
        w_spectrogram.setScrollSpeed(1000);
    } else if (n == 1) {
        w_spectrogram.numHorizAxisDivs = 6;
        w_spectrogram.setScrollSpeed(200);
    } else if (n == 2) {
        w_spectrogram.numHorizAxisDivs = 3;
        w_spectrogram.setScrollSpeed(100);
    } else if (n == 3) {
        w_spectrogram.numHorizAxisDivs = 3;
        w_spectrogram.setScrollSpeed(50);
    } else if (n == 4) {
        w_spectrogram.numHorizAxisDivs = 2;
        w_spectrogram.setScrollSpeed(25);
    }
    w_spectrogram.horizAxisLabelStrings.clear();
    w_spectrogram.fetchTimeStrings(w_spectrogram.numHorizAxisDivs);
}

void SpectrogramFreqScale(int n) {
    settings.spectFreqScaleSave = n;
    w_spectrogram.useMelScale = (n == 1); // 0=Linear, 1=Mel
    // Rebuild image dimensions for the new scale mode
    if (w_spectrogram.useMelScale) {
        w_spectrogram.dataImageH = w_spectrogram.nMelBands * 2;
    } else {
        w_spectrogram.dataImageH = w_spectrogram.vertAxisLabel[0] * 2;
    }
    w_spectrogram.dataImg = createImage(w_spectrogram.dataImageW, w_spectrogram.dataImageH, RGB);
    w_spectrogram.buildMelFilterBank();
}

void SpectrogramColormap(int n) {
    settings.spectColormapSave = n;
    w_spectrogram.currentColormap = n;
    w_spectrogram.colormapLUT = getColormapLUT(n);
}