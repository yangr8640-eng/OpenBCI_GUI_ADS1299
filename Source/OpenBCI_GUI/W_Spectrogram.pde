
//////////////////////////////////////////////////////
//                                                  //
//                  W_Spectrogram.pde               //
//                                                  //
//    PSD Plot: X = Frequency (Hz), Y = Power (dB)  //
//    Heatmap-style filled area with vertical color  //
//    gradient — red (0dB) to blue (-40dB).          //
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
    int paddingRight = 60;   // extra space for color bar on right
    int paddingTop = 8;
    int paddingBottom = 50;
    int graphX = 0;
    int graphY = 0;
    int graphW = 0;
    int graphH = 0;

    // Color bar fields
    int colorBarWidth = 14;
    int colorBarX = 0;
    int colorBarGap = 10;

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
    private float[][] cachedSpectra;       // [nchan][specSize] — per-channel FFT amplitudes
    private float[] workBuffer;            // reused float buffer for FFT input
    private float dBMin = -40.0f;
    private float dBMax = 0.0f;

    // Gradient endpoints: red = high power (0dB), blue = low power (-40dB)
    private final color highPowerColor = #FF3030;
    private final color lowPowerColor  = #3080FF;

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
        computePlotLayout();

        // Set defaults
        settings.spectMaxFrqSave = 1;
        settings.spectFreqScaleSave = 0;
        settings.spectColormapSave = 0;
        vertAxisLabel = vertAxisLabels[settings.spectMaxFrqSave];

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

            // Draw heatmap-style PSD fill for both channel groups
            drawHeatmapPSD(topSpectrum);
            drawHeatmapPSD(botSpectrum);

            // Draw color bar on the right
            drawColorBar();

            // Draw legend for channel groups
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
        computePlotLayout();
        if (spectChanSelectTop.isVisible()) {
            graphY += navH * 2;
            graphH -= navH * 2;
            computePlotLayout();
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
        // X-axis label
        pushStyle();
            fill(0);
            textSize(14);
            text("Frequency (Hz)", graphX + graphW/2 - textWidth("Frequency (Hz)")/3, y + h - 9);
        popStyle();

        // Plot border
        pushStyle();
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

            int numXTicks = 5;
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
                    int labelIdx = round(frac * (vertAxisLabel.length - 1));
                    label = Integer.toString(vertAxisLabel[labelIdx]);
                }
                text(label, tx - textWidth(label)/2, axisY + tickMarkSize * 3);
            }
        popStyle();

        // Y-axis label (rotated)
        pushStyle();
            pushMatrix();
                translate(18, graphY + graphH/2 + textWidth("Power (dB)")/2);
                rotate(radians(-90));
                fill(0);
                textSize(14);
                text("Power (dB)", 0, 0);
            popMatrix();
        popStyle();

        // Y-axis ticks (dB)
        pushStyle();
            tickMarkSize = 7;
            float axisX = graphX;
            stroke(0);
            fill(0);
            textSize(12);
            strokeWeight(2);
            float[] dbTicks = {0, -10, -20, -30, -40};
            for (int i = 0; i < dbTicks.length; i++) {
                float frac = (dbTicks[i] - dBMin) / (dBMax - dBMin);
                float ty = graphY + (1.0f - frac) * graphH;
                line(axisX, ty, axisX - tickMarkSize, ty);
                String label = Integer.toString((int)dbTicks[i]);
                text(label, axisX - tickMarkSize*2 - textWidth(label), ty + 4);
            }
        popStyle();

        // Formula annotation (small text, top-right of plot area)
        pushStyle();
            fill(0);
            textSize(9);
            textAlign(RIGHT, TOP);
            text("dB = 10·log₁₀(P) - 10·log₁₀(Pmax)", graphX + graphW - 6, graphY + 4);
        popStyle();
    }

    // ============ GRID, CURVE & COLOR BAR ============

    private void drawGridLines() {
        float[] dbTicks = {0, -10, -20, -30, -40};

        // Horizontal dashed grid lines at dB ticks
        for (int i = 0; i < dbTicks.length; i++) {
            float frac = (dbTicks[i] - dBMin) / (dBMax - dBMin);
            float gy = graphY + (1.0f - frac) * graphH;
            drawDashedLine(graphX, gy, graphX + graphW, gy, color(200), 8, 4);
        }

        // Vertical dashed grid lines at frequency tick positions
        int numXTicks = 5;
        for (int i = 0; i < numXTicks; i++) {
            float frac = (float)i / (numXTicks - 1);
            float gx = graphX + frac * graphW;
            drawDashedLine(gx, graphY, gx, graphY + graphH, color(200), 8, 4);
        }
    }

    /**
     * Draw PSD as a heatmap-style filled area: for each frequency bin,
     * the area from baseline (-40dB) up to the data value is filled with
     * a vertical color gradient — red at the top (0dB, high power),
     * blue at the bottom (-40dB, low power).
     *
     * Uses filled rectangles for clean, crisp horizontal color bands.
     */
    private void drawHeatmapPSD(float[] data) {
        if (data == null || data.length < 2) return;

        int n = min(data.length, numDisplayBins);
        float baselineY = graphY + graphH;

        int bands = 160;  // fine bands for smooth gradient
        float bandH = graphH / (float)bands;

        noStroke();
        for (int band = 0; band < bands; band++) {
            float bandTop = graphY + band * bandH;
            float bandMidY = graphY + (band + 0.5f) * bandH;
            // band 0 = top (red, near 0dB), band N-1 = bottom (blue, near -40dB)
            float frac = (float)band / (float)(bands - 1);
            color bandColor = lerpColor(lowPowerColor, highPowerColor, 1.0f - frac);
            fill(bandColor);

            // Draw filled rectangular segments across freq bins above this band
            boolean drawing = false;
            float segStart = 0;
            for (int i = 0; i < n; i++) {
                float px = graphX + (float)i / (numDisplayBins - 1) * graphW;
                float dataY = graphY + (1.0f - data[i]) * graphH;
                dataY = constrain(dataY, graphY, baselineY);
                boolean above = (dataY <= bandMidY);

                if (above && !drawing) {
                    segStart = px;
                    drawing = true;
                } else if (!above && drawing) {
                    rect(segStart, bandTop, px - segStart, bandH);
                    drawing = false;
                }
            }
            if (drawing) {
                float lastX = graphX + (float)(n - 1) / (numDisplayBins - 1) * graphW;
                rect(segStart, bandTop, lastX - segStart, bandH);
            }
        }

        // Subtle outline curve on top of the heatmap fill
        noFill();
        stroke(0, 80);
        strokeWeight(1.2f);
        beginShape(LINE_STRIP);
        for (int i = 0; i < n; i++) {
            float px = graphX + (float)i / (numDisplayBins - 1) * graphW;
            float py = graphY + (1.0f - data[i]) * graphH;
            py = constrain(py, graphY, baselineY);
            vertex(px, py);
        }
        endShape();
    }

    /**
     * Draw vertical color bar on the right: red (top, 0dB) → blue (bottom, -40dB).
     */
    private void drawColorBar() {
        int barH = graphH;
        int segments = 128;  // number of gradient steps

        pushStyle();
        noStroke();
        for (int i = 0; i < segments; i++) {
            float frac = (float)i / (segments - 1);  // 0=top(0dB,red), 1=bottom(-40dB,blue)
            color c = lerpColor(lowPowerColor, highPowerColor, 1.0f - frac);  // frac=0→red, frac=1→blue
            fill(c);
            float y0 = graphY + frac * barH;
            float segH = (barH / (float)segments) + 1;  // +1 to avoid gaps
            rect(colorBarX, y0, colorBarWidth, segH);
        }

        // Color bar border
        noFill();
        stroke(0);
        strokeWeight(1);
        rect(colorBarX, graphY, colorBarWidth, barH);

        // dB labels next to color bar
        fill(0);
        textSize(11);
        textAlign(LEFT, CENTER);
        float[] dbTicks = {0, -10, -20, -30, -40};
        for (int i = 0; i < dbTicks.length; i++) {
            float frac = (dbTicks[i] - dBMin) / (dBMax - dBMin);
            float ly = graphY + (1.0f - frac) * graphH;
            // Tick mark
            stroke(0);
            strokeWeight(1);
            line(colorBarX + colorBarWidth, ly, colorBarX + colorBarWidth + 5, ly);
            // Label
            noStroke();
            String label = Integer.toString((int)dbTicks[i]);
            text(label, colorBarX + colorBarWidth + 7, ly);
        }
        popStyle();
    }

    private void drawLegend() {
        int legendX = graphX + 6;
        int legendY = graphY + 6;
        int swatchW = 20, swatchH = 3;

        pushStyle();
        textSize(11);
        textAlign(LEFT, CENTER);

        // Top group
        stroke(#FF3030);
        strokeWeight(3);
        line(legendX, legendY, legendX + swatchW, legendY);
        fill(0);
        noStroke();
        text("Ch Top", legendX + swatchW + 4, legendY);

        // Bottom group
        stroke(#3080FF);
        strokeWeight(3);
        line(legendX, legendY + 14, legendX + swatchW, legendY + 14);
        fill(0);
        text("Ch Bot", legendX + swatchW + 4, legendY + 14);

        popStyle();
    }

    // ============ DASHED LINE HELPER ============

    private void drawDashedLine(float x1, float y1, float x2, float y2, color c, float dashLen, float gapLen) {
        stroke(c);
        strokeWeight(1);
        float dx = x2 - x1;
        float dy = y2 - y1;
        float len = sqrt(dx*dx + dy*dy);
        if (len < 1) return;
        float ux = dx / len;
        float uy = dy / len;
        boolean drawing = true;
        float pos = 0;
        while (pos < len) {
            float segLen = drawing ? dashLen : gapLen;
            if (pos + segLen > len) segLen = len - pos;
            if (drawing) {
                line(x1 + ux*pos, y1 + uy*pos, x1 + ux*(pos+segLen), y1 + uy*(pos+segLen));
            }
            pos += segLen;
            drawing = !drawing;
        }
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

    void computePlotLayout() {
        graphX = x + paddingLeft;
        graphY = y + paddingTop;
        graphW = w - paddingRight - paddingLeft;
        graphH = h - paddingBottom - paddingTop;
        colorBarX = graphX + graphW + colorBarGap;
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
    // Colormap dropdown no longer used for theme selection;
    // color is now fixed red→blue gradient by power level.
    // Keeping callback to avoid breaking settings persistence.
}
