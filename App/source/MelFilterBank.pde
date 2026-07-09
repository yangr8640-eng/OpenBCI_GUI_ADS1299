//////////////////////////////////////////////////////
//                                                  //
//               MelFilterBank.pde                   //
//                                                  //
//  Creates triangular mel-scale filterbanks and    //
//  applies them to linear FFT magnitude spectra.   //
//  Pure Java — no Processing dependencies.         //
//                                                  //
//////////////////////////////////////////////////////

/**
 * A mel-frequency filterbank using standard overlapping triangular filters.
 *
 * Construction precomputes a weight matrix so that applying the filterbank
 * to a linear spectrum is a single matrix multiplication per frame.
 */
class MelFilterBank {

  int nFFT;           // number of FFT bins in the LINEAR input spectrum (= specSize)
  int nMels;           // number of mel bands to output
  float sampleRate;    // sample rate in Hz
  float fMin;          // lowest frequency (Hz)
  float fMax;          // highest frequency (Hz)

  float[][] weights;   // [nMels][nFFT] — precomputed filter weights
  int[] binIndices;    // cache: which linear bin index each mel band center corresponds to

  /**
   * Mel scale conversion (O'Shaughnessy's formula, used by librosa).
   */
  float hzToMel(float hz) {
    return 2595.0f * (float)Math.log10(1.0 + hz / 700.0);
  }

  float melToHz(float mel) {
    return 700.0f * (float)(Math.pow(10.0, mel / 2595.0) - 1.0);
  }

  /**
   * @param _nFFT        number of FFT bins in the input (e.g., fft.specSize())
   * @param _nMels       desired number of mel bands
   * @param _sampleRate  sample rate in Hz
   * @param _fMin        lowest center frequency in Hz (usually 0 or 0.5)
   * @param _fMax        highest center frequency in Hz
   */
  MelFilterBank(int _nFFT, int _nMels, float _sampleRate, float _fMin, float _fMax) {
    nFFT = _nFFT;
    nMels = _nMels;
    sampleRate = _sampleRate;
    fMin = max(_fMin, 0.0f);
    fMax = min(_fMax, sampleRate / 2.0f);

    weights = new float[nMels][nFFT];
    binIndices = new int[nMels];
    buildFilterbank();
  }

  /**
   * Precompute the triangular overlapping filter weights matrix.
   *
   * For each mel band m:
   *   - The mel center for band m is the equispaced point between mel(fMin) and mel(fMax)
   *   - The triangular filter for band m spans from centre of band m-1 to center of band m+1
   *   - Weights sum to 1 across each filter (normalized by area)
   */
  private void buildFilterbank() {
    float melMin = hzToMel(fMin);
    float melMax = hzToMel(fMax);
    float melStep = (melMax - melMin) / (nMels + 1);

    // Precompute the FFT bin center frequency for every bin
    float[] binFreqs = new float[nFFT];
    for (int b = 0; b < nFFT; b++) {
      binFreqs[b] = b * sampleRate / (2.0f * (nFFT - 1));  // Nyquist = nFFT-1
    }

    for (int m = 0; m < nMels; m++) {
      // Mel center frequencies for this triangular filter:
      // left foot = mel band m, center = mel band m+1, right foot = mel band m+2
      float melLeft   = melMin +  m      * melStep;
      float melCenter = melMin + (m + 1) * melStep;
      float melRight  = melMin + (m + 2) * melStep;

      float hzLeft   = melToHz(melLeft);
      float hzCenter = melToHz(melCenter);
      float hzRight  = melToHz(melRight);

      // Record the bin closest to center (for axis labeling)
      binIndices[m] = freqToBin(hzCenter);

      // Build triangular weights for each FFT bin
      float weightSum = 0.0f;
      for (int b = 0; b < nFFT; b++) {
        float bHz = binFreqs[b];

        if (bHz <= hzLeft || bHz >= hzRight) {
          weights[m][b] = 0.0f;
        } else if (bHz <= hzCenter) {
          // Rising ramp: left → center
          weights[m][b] = (bHz - hzLeft) / (hzCenter - hzLeft);
        } else {
          // Falling ramp: center → right
          weights[m][b] = (hzRight - bHz) / (hzRight - hzCenter);
        }
        weightSum += weights[m][b];
      }

      // Normalize so each filter has unit area
      if (weightSum > 0.0f) {
        for (int b = 0; b < nFFT; b++) {
          weights[m][b] /= weightSum;
        }
      }
    }
  }

  /**
   * Apply the mel filterbank to a linear amplitude spectrum.
   *
   * @param linearSpectrum  float[specSize] — single-sided amplitude spectrum per FFT bin
   * @return                float[nMels] — mel-band energies
   */
  float[] apply(float[] linearSpectrum) {
    float[] melSpec = new float[nMels];

    for (int m = 0; m < nMels; m++) {
      float sum = 0.0f;
      for (int b = 0; b < min(nFFT, linearSpectrum.length); b++) {
        sum += weights[m][b] * linearSpectrum[b];
      }
      melSpec[m] = sum;
    }

    return melSpec;
  }

  /**
   * Convert a frequency in Hz to the nearest FFT bin index.
   */
  private int freqToBin(float hz) {
    return round(hz * 2.0f * (nFFT - 1) / sampleRate);
  }

  /**
   * Given a mel band index, return the approximate center frequency in Hz.
   */
  float getMelBandCenterHz(int melBand) {
    if (melBand < 0 || melBand >= nMels) return 0.0f;
    float melMin = hzToMel(fMin);
    float melMax = hzToMel(fMax);
    float melStep = (melMax - melMin) / (nMels + 1);
    return melToHz(melMin + (melBand + 1) * melStep);
  }
}
