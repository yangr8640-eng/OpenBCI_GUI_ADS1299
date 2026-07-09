
//////////////////////////////////////////////////////
//                                                  //
//                  W_Spectrogram.pde               //
//                                                  //
//    PSD Plot: X = Frequency (Hz), Y = Power (dB)  //
//    Overlaid filled-area curves for two channel   //
//    groups with mel scale and colormap support.   //
//                                                  //
//    Created by: Richard Waltman, September 2019   //
//    Enhanced: Mel scale + PSD plot, July 2026     //
//                                                  //
//////////////////////////////////////////////////////

class W_Spectrogram extends Widget {

    //to see all core variables/methods of the Widget class, refer to Widget.pde
    public ChannelSelect spectChanSelectTop;
    public ChannelSelect spectChanSelectBot;
    private boolean chanSelectWasOpen = false;
    List<controlP5.Controller> cp5ElementsToCheck = new ArrayList<controlP5.Controller>();

    // PSD Plot Fields
    int paddingLeft = 54;
    int paddingRight = 26;
    int paddingTop = 8;
    int paddingBottom = 50;
    int graphX = 0;
    int graphY = 0;
    int graphW = 0;
    int graphH = 0;

    final int[][] vertAxisLabels = {
        {0, 5, 10, 15, 20},
        {0, 10, 20, 30, 40},
        {0, 15, 30, 45, 60},
        {0, 25, 50, 75, 100},
        {0, 30, 60, 90, 120},
        {0, 63, 125, 188, 250}
    };
    int[] vertAxisLabel;

    // PSD data processing
    private MelFilterBank melFilterBank;
    private int nMelBands = 64;
    private boolean useMelScale = false;
    private int currentColorTheme = 0;     // 0=Inferno, 1=Jet, 2=Viridis, 3=BlueGreen
    private float[][] cachedSpectra;       // [nchan][specSize] — per-channel FFT amplitudes
    private float[] workBuffer;            // reused float buffer for FFT input
    private float dBMin = -40.0f;
    private float dBMax = 0.0f;

    // Curve colors per theme {top, bot}
    private final color[][] themeColors = {
        {#FF3030, #3080FF},  // Inferno: red + blue
        {#00BFFF, #FF4500},  // Jet: cyan + red-orange
        {#5EC962, #3B528B},  // Viridis: green + blue
        {#00C060, #004080}   // BlueGreen: green + navy
    };
    private color topColor, botColor;

    // Cached display data
    private float[] topSpectrum;
    private float[] botSpectrum;
    private int numDisplayBins;
    private boolean wasRunning = false;

    W_Spectrogram(PApplet _parent){
        super(_parent);

        //Add channel select dropdown to this widget
        spectChanSelectTop = new ChannelSelect(pApplet, this, x, y, w, navH, "Spectrogram_Channels_Top");
        spectChanSelectBot = new ChannelSelect(pApplet, this, x, y + navH, w, navH, "Spectrogram_Channels_Bot");
        activateDefaultChannels();
        spectChanSelectTop.setIsDualChannelSelect(true);
        spectChanSelectBot.setIsDualChannelSelect(true);
        spectChanSelectBot.setIsFirstRowChannelSelect(false);
        cp5ElementsToCheck.addAll(spectChanSelectTop.getCp5ElementsForOverlapCheck());
        cp5ElementsToCheck.addAll(spectChanSelectBot.getCp5ElementsForOverlapCheck());

        // Calculate plot area
        graphX = x + paddingLeft;
        graphY = y + paddingTop;
        graphW = w - paddingRight - paddingLeft;
        graphH = h - paddingBottom - paddingTop;

        // Set defaults
        settings.spectMaxFrqSave = 1;
        settings.spectFreqScaleSave = 0;
        settings.spectColormapSave = 0;
        vertAxisLabel = vertAxisLabels[settings.spectMaxFrqSave];

        // Initialize curve colors
        currentColorTheme = settings.spectColormapSave;
        updateCurveColors();

        // Set up dropdowns
        addDropdown("SpectrogramMaxFreq", "Max Freq", Arrays.asList(settings.spectMaxFrqArray), settings.spectMaxFrqSave);
        addDropdown("SpectrogramFreqScale", "Freq Scale", Arrays.asList("Linear", "Mel"), settings.spectFreqScaleSave);
        addDropdown("SpectrogramColormap", "Colormap", Arrays.asList("Inferno", "Jet", "Viridis", "BlueGreen"), settings.spectColormapSave);

        // Determine initial number of display bins
        numDisplayBins = fftBuff[0].specSize();

        // Build the mel filterbank
        buildMelFilterBank();
    }

    void update(){
        super.update();

        // Update channel checkboxes and active channels
        spectChanSelectTop.update(x, y, w);
        spectChanSelectBot.update(x, y + navH, w);

        // Sync bottom channel select visibility with top
        if (chanSelectWasOpen != spectChanSelectTop.isVisible()) {
            spectChanSelectBot.setIsVisible(spectChanSelectTop.isVisible());
            chanSelectWasOpen = spectChanSelectTop.isVisible();
            flexSpectrogramSizeAndPosition();
        }

        if (spectChanSelectTop.isVisible()) {
            lockElementsOnOverlapCheck(cp5ElementsToCheck);
        }

        if (currentBoard.isStreaming()) {
            computeUnsmooothedSpectra();
        }

        // State change check
        if (currentBoard.isStreaming() && !wasRunning) {
            onStartRunning();
        } else if (!currentBoard.isStreaming() && wasRunning) {
            onStopRunning();
        }
    }

    private void onStartRunning() {
        wasRunning = true;
        buildMelFilterBank();
        int specSize = fftBuff[0].specSize();
        cachedSpectra = new float[nchan][specSize];
        workBuffer = new float[getNfftSafe()];
        // Pre-allocate display arrays
        numDisplayBins = useMelScale ? nMelBands : specSize;
        topSpectrum = new float[numDisplayBins];
        botSpectrum = new float[numDisplayBins];
    }

    private void onStopRunning() {
        wasRunning = false;
    }

    public void draw(){
        super.draw();

        pushStyle();
        fill(255);
        rect(x, y, w, h);
        popStyle();

        if (currentBoard.isStreaming()) {
            // Compute display data for both channel groups
            computeSpectrumForGroup(spectChanSelectTop, topSpectrum);
            computeSpectrumForGroup(spectChanSelectBot, botSpectrum);

            pushStyle();
            // Draw grid lines
            drawGridLines();

            // Draw filled area curves
            color topFill = color(red(topColor), green(topColor), blue(topColor), 80);
            color botFill = color(red(botColor), green(botColor), blue(botColor), 80);
            drawFilledCurve(topSpectrum, topFill, topColor);
            drawFilledCurve(botSpectrum, botFill, botColor);

            // Draw legend
            drawLegend();
            popStyle();
        }

        spectChanSelectTop.draw();
        spectChanSelectBot.draw();
        drawAxes();
    }

    public void screenResized(){
        super.screenResized();

        spectChanSelectTop.screenResized(pApplet);
        spectChanSelectBot.screenResized(pApplet);
        graphX = x + paddingLeft;
        graphY = y + paddingTop;
        graphW = w - paddingRight - paddingLeft;
        graphH = h - paddingBottom - paddingTop;
        if (spectChanSelectTop.isVisible()) {
            graphY += navH * 2;
            graphH -= navH * 2;
        }
    }

    void mousePressed(){
        super.mousePressed();
        spectChanSelectTop.mousePressed(this.dropdownIsActive);
        spectChanSelectBot.mousePressed(this.dropdownIsActive);
    }

    void mouseReleased(){
        super.mouseReleased();
    }

    // ============ AXES ============

    void drawAxes() {
        pushStyle();
            fill(0);
            textSize(14);
            // X-axis label
            text("Frequency (Hz)", x + w/2 - textWidth("Frequency (Hz)")/3, y + h - 9);
            noFill();
            stroke(0);
            strokeWeight(2);
            rect(graphX, graphY, graphW, graphH);
        popStyle();

        // X-axis ticks (frequency)
        pushStyle();
            int tickMarkSize = 7;
            float axisY = graphY + graphH;
            stroke(0);
            fill(0);
            strokeWeight(2);
            textSize(11);

            int numXTicks = 5;  // 0, 25%, 50%, 75%, 100% of range
            for (int i = 0; i < numXTicks; i++) {
                float frac = (float)i / (numXTicks - 1);
                float tx = graphX + frac * graphW;
                line(tx, axisY, tx, axisY + tickMarkSize);

                String label;
                if (useMelScale && melFilterBank != null) {
                    int melIdx = round(frac * (nMelBands - 1));
                    float hz = melFilterBank.getMelBandCenterHz(melIdx);
                    label = nf(hz, 0, 1);
                } else {
                    // Use vertAxisLabel for evenly spaced labels
                    int labelIdx = round(frac * (vertAxisLabel.length - 1));
                    label = Integer.toString(vertAxisLabel[labelIdx]);
                }
                text(label, tx - textWidth(label)/2, axisY + tickMarkSize * 3);
            }
        popStyle();

        // Y-axis label (rotated)
        pushStyle();
            pushMatrix();
                rotate(radians(-90));
                translate(-h/2 - textWidth("Power (dB)")/3, 20);
                fill(0);
                textSize(14);
                text("Power (dB)", -y, x);
            popMatrix();
        popStyle();

        // Y-axis ticks (dB)
        pushStyle();
            float axisX = graphX;
            stroke(0);
            fill(0);
            textSize(12);
            strokeWeight(2);
            float[] dbTicks = {0, -10, -20, -30, -40};
            for (int i = 0; i < dbTicks.length; i++) {
                float frac = (dbTicks[i] - dBMin) / (dBMax - dBMin); // 0dB→1.0, -40dB→0.0
                float ty = graphY + (1.0f - frac) * graphH;
                line(axisX, ty, axisX - tickMarkSize, ty);
                String label = Integer.toString((int)dbTicks[i]);
                text(label, axisX - tickMarkSize*2 - textWidth(label), ty + 4);
            }
        popStyle();
    }

    // ============ GRID & CURVE DRAWING ============

    private void drawGridLines() {
        stroke(200, 200, 200);
        strokeWeight(1);
        float[] dbTicks = {0, -10, -20, -30, -40};
        for (int i = 0; i < dbTicks.length; i++) {
            float frac = (dbTicks[i] - dBMin) / (dBMax - dBMin);
            float gy = graphY + (1.0f - frac) * graphH;
            for (float gx = graphX; gx <= graphX + graphW; gx += 5) {
                if ((int)(gx / 5) % 2 == 0) {
                    point(gx, gy);
                }
            }
        }
    }

    private void drawFilledCurve(float[] data, color fillColor, color lineColor) {
        if (data == null || data.length < 2) return;

        float baselineY = graphY + graphH;
        int n = min(data.length, numDisplayBins);

        // Filled area using QUAD_STRIP
        noStroke();
        fill(fillColor);
        beginShape(QUAD_STRIP);
        for (int i = 0; i < n; i++) {
            float px = graphX + (float)i / (numDisplayBins - 1) * graphW;
            float py = graphY + (1.0f - data[i]) * graphH;
            py = constrain(py, graphY, graphY + graphH);
            vertex(px, baselineY);
            vertex(px, py);
        }
        endShape();

        // Outline line
        noFill();
        stroke(lineColor);
        strokeWeight(1.5f);
        beginShape(LINE_STRIP);
        for (int i = 0; i < n; i++) {
            float px = graphX + (float)i / (numDisplayBins - 1) * graphW;
            float py = graphY + (1.0f - data[i]) * graphH;
            py = constrain(py, graphY, graphY + graphH);
            vertex(px, py);
        }
        endShape();
    }

    private void drawLegend() {
        int legendX = graphX + graphW - 140;
        int legendY = graphY + 8;
        int swatchSize = 12;

        pushStyle();
        textSize(11);
        textAlign(LEFT, CENTER);

        // Top group
        fill(topColor);
        noStroke();
        rect(legendX, legendY, swatchSize, swatchSize);
        fill(0);
        text("Ch Top", legendX + swatchSize + 5, legendY + swatchSize/2);

        // Bottom group
        fill(botColor);
        rect(legendX, legendY + swatchSize + 6, swatchSize, swatchSize);
        fill(0);
        text("Ch Bot", legendX + swatchSize + 5, legendY + swatchSize + 6 + swatchSize/2);

        popStyle();
    }

    // ============ SPECTRUM COMPUTATION ============

    private void computeUnsmooothedSpectra() {
        int nfft = getNfftSafe();
        if (workBuffer == null || workBuffer.length != nfft) {
            workBuffer = new float[nfft];
        }

        java.util.Set<Integer> allActiveChans = new java.util.HashSet<Integer>();
        for (int i : spectChanSelectTop.activeChan) allActiveChans.add(i);
        for (int i : spectChanSelectBot.activeChan) allActiveChans.add(i);

        for (int chan : allActiveChans) {
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

            fftBuffSpectrogram[chan].forward(workBuffer);

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
     * Compute full-resolution dB-normalized spectrum for a channel group.
     * Averages across active channels, applies mel filterbank (if enabled),
     * converts to dB, and normalizes to [0, 1].
     */
    private void computeSpectrumForGroup(ChannelSelect sel, float[] dest) {
        if (dest == null) return;
        // Zero out destination
        for (int i = 0; i < dest.length; i++) dest[i] = 0.0f;

        if (sel.activeChan.size() == 0) return;

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

        // Apply mel filterbank if enabled
        float[] displayData;
        int displayLen;
        if (useMelScale && melFilterBank != null) {
            displayData = melFilterBank.apply(avgAmp);
            displayLen = min(nMelBands, dest.length);
        } else {
            displayData = avgAmp;
            displayLen = min(specSize, dest.length);
        }

        // Convert to dB and normalize
        float maxAmp = 1e-10f;
        for (int i = 0; i < displayLen; i++) {
            if (displayData[i] > maxAmp) maxAmp = displayData[i];
        }
        for (int i = 0; i < displayLen; i++) {
            float val = max(displayData[i], 1e-10f);
            float dbVal = 10.0f * (float)Math.log10(val) - 10.0f * (float)Math.log10(maxAmp);
            dest[i] = constrain((dbVal - dBMin) / (dBMax - dBMin), 0.0f, 1.0f);
        }
    }

    private void buildMelFilterBank() {
        try {
            int nfft = getNfftSafe();
            float sr = currentBoard.getSampleRate();
            if (sr <= 0) return;
            float fMax = vertAxisLabel[vertAxisLabel.length - 1];
            int specSize = nfft / 2 + 1;
            melFilterBank = new MelFilterBank(specSize, nMelBands, sr, 0.5f, fMax);
            if (useMelScale) {
                numDisplayBins = nMelBands;
            } else {
                numDisplayBins = specSize;
            }
            // Reallocate display arrays
            topSpectrum = new float[numDisplayBins];
            botSpectrum = new float[numDisplayBins];
        } catch (Exception e) {
            // Silently handle
        }
    }

    private void updateCurveColors() {
        int idx = constrain(currentColorTheme, 0, themeColors.length - 1);
        topColor = themeColors[idx][0];
        botColor = themeColors[idx][1];
    }

    // ============ CHANNEL & LAYOUT HELPERS ============

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
            topChansToActivate = new int[]{0, 2, 4, 6, 8, 10, 12, 14};
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
};

// ============ GLOBAL DROPDOWN CALLBACKS ============

void SpectrogramMaxFreq(int n) {
    settings.spectMaxFrqSave = n;
    w_spectrogram.vertAxisLabel = w_spectrogram.vertAxisLabels[n];
    w_spectrogram.buildMelFilterBank();
}

void SpectrogramFreqScale(int n) {
    settings.spectFreqScaleSave = n;
    w_spectrogram.useMelScale = (n == 1);
    w_spectrogram.buildMelFilterBank();
}

void SpectrogramColormap(int n) {
    settings.spectColormapSave = n;
    w_spectrogram.currentColorTheme = n;
    w_spectrogram.updateCurveColors();
}
