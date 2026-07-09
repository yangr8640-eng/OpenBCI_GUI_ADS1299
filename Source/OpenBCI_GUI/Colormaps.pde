//////////////////////////////////////////////////////
//                                                  //
//                  Colormaps.pde                    //
//                                                  //
//    Color LUT provider for spectrogram display    //
//    Precomputed 256-entry colormap lookup tables  //
//                                                  //
//////////////////////////////////////////////////////

// Keypoint-based colormap definitions.
// Each keypoint is {R, G, B, position} with position from 0.0 to 1.0.
// RGB values are 0-255.

final float[][] INFERNO_KEYS = {
  {  0,   0,   4, 0.00f},   // near-black
  { 40,  11,  84, 0.15f},   // dark purple
  {101,  21, 110, 0.30f},   // purple
  {159,  42,  99, 0.45f},   // magenta-red
  {212,  72,  66, 0.60f},   // red
  {245, 125,  21, 0.80f},   // orange
  {252, 255, 164, 1.00f}    // yellow-white
};

final float[][] JET_KEYS = {
  {  0,   0, 131, 0.00f},   // dark blue
  {  0,  60, 170, 0.15f},   // blue
  {  5, 255, 255, 0.35f},   // cyan
  {255, 255,   0, 0.55f},   // yellow
  {255, 100,   0, 0.75f},   // orange
  {128,   0,   0, 1.00f}    // dark red
};

final float[][] VIRIDIS_KEYS = {
  { 68,   1,  84, 0.00f},   // dark purple
  { 59,  82, 139, 0.20f},   // blue
  { 33, 145, 140, 0.45f},   // teal
  { 94, 201,  98, 0.65f},   // green
  {253, 231,  37, 1.00f}    // yellow
};

final float[][] BLUEGREEN_KEYS = {
  {  0,   0,  64, 0.00f},   // navy
  {  0,  64, 128, 0.15f},   // dark blue
  {  0, 128, 128, 0.30f},   // teal
  {  0, 192,  96, 0.50f},   // green
  {128, 255,   0, 0.70f},   // lime
  {255, 255, 128, 0.85f},   // pale yellow
  {255, 255, 255, 1.00f}    // white
};

// Lookup table size constant
final int COLORMAP_LUT_SIZE = 256;

/**
 * Build a color lookup table from keypoint definitions.
 * Linearly interpolates RGB between consecutive keypoints.
 * Uses Processing's color() function for the output.
 *
 * @param keypoints  array of {R, G, B, position} arrays, sorted by position
 * @param lutSize    number of entries in the output LUT (typically 256)
 * @return           color[] of Processing color values
 */
color[] buildColormapLUT(float[][] keypoints, int lutSize) {
  color[] lut = new color[lutSize];

  for (int i = 0; i < lutSize; i++) {
    float t = (float)i / (float)(lutSize - 1);

    // Find the two surrounding keypoints
    int klo = 0;
    int khi = keypoints.length - 1;
    for (int k = 0; k < keypoints.length - 1; k++) {
      if (t >= keypoints[k][3] && t <= keypoints[k + 1][3]) {
        klo = k;
        khi = k + 1;
        break;
      }
    }

    // Linear interpolation between klo and khi
    float segStart = keypoints[klo][3];
    float segEnd   = keypoints[khi][3];
    float frac;
    if (segEnd == segStart) {
      frac = 0.0f;
    } else {
      frac = (t - segStart) / (segEnd - segStart);
    }
    frac = constrain(frac, 0.0f, 1.0f);

    int r = (int)(keypoints[klo][0] + frac * (keypoints[khi][0] - keypoints[klo][0]));
    int g = (int)(keypoints[klo][1] + frac * (keypoints[khi][1] - keypoints[klo][1]));
    int b = (int)(keypoints[klo][2] + frac * (keypoints[khi][2] - keypoints[klo][2]));

    lut[i] = color(r, g, b);
  }

  return lut;
}

/**
 * Convenience: get a prebuilt LUT by colormap index.
 * 0 = Inferno, 1 = Jet, 2 = Viridis, 3 = BlueGreen
 */
color[] getColormapLUT(int index) {
  switch (index) {
    case 0:  return buildColormapLUT(INFERNO_KEYS, COLORMAP_LUT_SIZE);
    case 1:  return buildColormapLUT(JET_KEYS, COLORMAP_LUT_SIZE);
    case 2:  return buildColormapLUT(VIRIDIS_KEYS, COLORMAP_LUT_SIZE);
    case 3:
    default: return buildColormapLUT(BLUEGREEN_KEYS, COLORMAP_LUT_SIZE);
  }
}
