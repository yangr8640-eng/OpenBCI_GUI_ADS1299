import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.Arrays;
import java.util.List;

/**
 * Headless smoke test for the packaged ADS1299 TCP implementation.
 *
 * Compile this class against App/lib/* and run it from the repository root.
 */
public final class ADS129xTcpIntegrationSmokeTest {
    private static final int CHANNEL_COUNT = 16;
    private static final int TOTAL_CHANNEL_COUNT = 21;
    private static final int BATTERY_PERCENT = 97;
    private static final int GAIN = 24;
    private static final int PERFORMANCE_SAMPLE_RATE = 2000;
    private static final int PERFORMANCE_SAMPLE_COUNT = 2000;
    private static final int SAMPLES_PER_FRAME = 5;
    private static final double ADS1299_LSB_UV = 4500000.0 / ((1 << 23) - 1);

    private ADS129xTcpIntegrationSmokeTest() {
    }

    public static void main(String[] args) {
        try {
            OpenBCI_GUI app = new OpenBCI_GUI();
            verifyConfiguredDataDirectory(app);
            verifyParserSupportsAllSampleRates(app);
            verifyTcpStreamingAt2000Hz(app);
            System.out.println("ADS1299 TCP integration smoke test passed.");
            System.exit(0);
        } catch (Throwable error) {
            error.printStackTrace();
            System.exit(1);
        }
    }

    private static void verifyConfiguredDataDirectory(OpenBCI_GUI app) {
        String configuredPath = System.getenv("OPENBCI_GUI_DATA_DIR");
        if (configuredPath == null || configuredPath.trim().isEmpty()) {
            throw new AssertionError("OPENBCI_GUI_DATA_DIR must be set for this smoke test");
        }

        OpenBCI_GUI.DirectoryManager manager = app.new DirectoryManager();
        String expectedPath = new File(configuredPath).getAbsolutePath() + File.separator;
        assertEquals(expectedPath, manager.getGuiDataPath(), "configured GUI data path");
        assertTrue(manager.init(), "configured GUI data directory should initialize");
        assertTrue(new File(manager.getRecordingsPath()).isDirectory(), "Recordings directory should exist");
        assertTrue(new File(manager.getSettingsPath()).isDirectory(), "Settings directory should exist");
        assertTrue(new File(manager.getConsoleDataPath()).isDirectory(), "Console_Data directory should exist");
    }

    private static void verifyParserSupportsAllSampleRates(OpenBCI_GUI app) throws IOException {
        int[] sampleRates = {250, 500, 1000, 2000};
        for (int sampleRate : sampleRates) {
            OpenBCI_GUI.ADS129xTcpParser parser = app.new ADS129xTcpParser();
            byte[] frameBytes = buildFrame(11L, 0, 2, sampleRate);

            List<OpenBCI_GUI.ADS129xTcpFrame> first = parser.feed(Arrays.copyOfRange(frameBytes, 0, 7), 7);
            assertEquals(0, first.size(), "partial frame should not parse");

            byte[] remainder = Arrays.copyOfRange(frameBytes, 7, frameBytes.length);
            List<OpenBCI_GUI.ADS129xTcpFrame> parsed = parser.feed(remainder, remainder.length);
            assertEquals(1, parsed.size(), "complete frame should parse");

            OpenBCI_GUI.ADS129xTcpFrame frame = parsed.get(0);
            assertTrue(frame.isEegFrame(), "frame should be EEG data");
            assertEquals(CHANNEL_COUNT, frame.channelCount, "channel count");
            assertEquals(sampleRate, frame.sampleRate, "sample rate");
            assertEquals(GAIN, frame.gain, "gain");
            assertEquals(2, frame.rawSamples.size(), "samples in frame");
            assertEquals(rawValue(0, 0), frame.rawSamples.get(0)[0], "signed 24-bit sample");
        }
    }

    private static void verifyTcpStreamingAt2000Hz(OpenBCI_GUI app) throws Exception {
        int port = findAvailablePort();
        OpenBCI_GUI.BoardADS129xTcp board = app.new BoardADS129xTcp(port, PERFORMANCE_SAMPLE_RATE);
        app.currentBoard = board;

        assertTrue(board.initialize(), "ADS1299 TCP board should initialize");
        board.startStreaming();

        long sendStarted = System.nanoTime();
        try {
            sendPerformanceFrames(port);
            int received = receiveAndValidate(board);
            assertEquals(PERFORMANCE_SAMPLE_COUNT, received, "received sample count");

            int tracked = board.getPacketLossTracker().getStreamPacketRecord().numReceived;
            assertEquals(PERFORMANCE_SAMPLE_COUNT, tracked, "packet tracker sample count");
        } finally {
            board.stopStreaming();
            board.uninitialize();
        }

        double elapsedSeconds = (System.nanoTime() - sendStarted) / 1_000_000_000.0;
        assertTrue(elapsedSeconds < 15.0, "2000 Hz integration test exceeded 15 seconds");
        System.out.println("Received and validated " + PERFORMANCE_SAMPLE_COUNT
            + " samples at 2000 Hz in " + elapsedSeconds + " seconds.");
    }

    private static void sendPerformanceFrames(int port) throws IOException {
        try (Socket socket = new Socket("127.0.0.1", port)) {
            socket.setTcpNoDelay(true);
            OutputStream output = socket.getOutputStream();
            long sequence = 0L;

            for (int sampleStart = 0; sampleStart < PERFORMANCE_SAMPLE_COUNT;
                 sampleStart += SAMPLES_PER_FRAME) {
                byte[] frame = buildFrame(sequence, sampleStart, SAMPLES_PER_FRAME, PERFORMANCE_SAMPLE_RATE);
                if (sequence == 0L) {
                    output.write(frame, 0, 7);
                    output.flush();
                    output.write(frame, 7, frame.length - 7);
                } else {
                    output.write(frame);
                }
                sequence++;
            }
            output.flush();
            socket.shutdownOutput();
        }
    }

    private static int receiveAndValidate(OpenBCI_GUI.BoardADS129xTcp board) throws Exception {
        int received = 0;
        double firstTimestamp = Double.NaN;
        long deadline = System.currentTimeMillis() + 10_000L;

        while (received < PERFORMANCE_SAMPLE_COUNT && System.currentTimeMillis() < deadline) {
            board.update();
            double[][] data = board.getFrameData();
            assertEquals(TOTAL_CHANNEL_COUNT, data.length, "total channel count");

            for (int column = 0; column < data[0].length; column++) {
                int sampleNumber = received++;
                assertNear(sampleNumber % 256, data[0][column], 0.0, "sample index");
                assertNear(BATTERY_PERCENT, data[17][column], 0.0, "battery value");

                double expectedUv = rawValue(sampleNumber, 0) * ADS1299_LSB_UV / GAIN;
                assertNear(expectedUv, data[1][column], 1e-6, "channel 1 microvolts");

                if (Double.isNaN(firstTimestamp)) {
                    firstTimestamp = data[19][column];
                }
                double expectedTimestamp = firstTimestamp + sampleNumber / (double) PERFORMANCE_SAMPLE_RATE;
                assertNear(expectedTimestamp, data[19][column], 1e-6, "sample timestamp");
            }

            if (data[0].length == 0) {
                Thread.sleep(10L);
            }
        }
        return received;
    }

    private static byte[] buildFrame(long sequence, int sampleStart, int sampleCount, int sampleRate)
            throws IOException {
        ByteArrayOutputStream bodyBytes = new ByteArrayOutputStream();
        DataOutputStream body = new DataOutputStream(bodyBytes);
        body.writeByte(0xA5);
        body.writeByte(0xA5);
        body.writeByte(0x01);
        body.writeByte(0x05);
        body.writeInt((int) sequence);
        body.writeByte(0x10);
        body.writeByte(100);
        body.writeByte(BATTERY_PERCENT);
        body.writeByte((sampleRateCode(sampleRate) << 4) | 0x00);
        body.writeShort(0);
        body.writeShort(sampleCount * CHANNEL_COUNT * 3);

        for (int sample = 0; sample < sampleCount; sample++) {
            int sampleNumber = sampleStart + sample;
            for (int channel = 0; channel < CHANNEL_COUNT; channel++) {
                writeInt24(body, rawValue(sampleNumber, channel));
            }
        }
        body.flush();

        byte[] bytesToChecksum = bodyBytes.toByteArray();
        int checksum = 0;
        for (byte value : bytesToChecksum) {
            checksum = (checksum + (value & 0xFF)) & 0xFFFF;
        }

        ByteArrayOutputStream frameBytes = new ByteArrayOutputStream();
        frameBytes.write(bytesToChecksum);
        DataOutputStream frame = new DataOutputStream(frameBytes);
        frame.writeShort(checksum);
        frame.writeByte(0x5A);
        frame.writeByte(0x5A);
        frame.flush();
        return frameBytes.toByteArray();
    }

    private static int rawValue(int sampleNumber, int channel) {
        return sampleNumber - 1000 + channel;
    }

    private static void writeInt24(DataOutputStream output, int value) throws IOException {
        int encoded = value & 0xFFFFFF;
        output.writeByte((encoded >>> 16) & 0xFF);
        output.writeByte((encoded >>> 8) & 0xFF);
        output.writeByte(encoded & 0xFF);
    }

    private static int sampleRateCode(int sampleRate) {
        switch (sampleRate) {
            case 250:
                return 7;
            case 500:
                return 6;
            case 1000:
                return 5;
            case 2000:
                return 4;
            default:
                throw new IllegalArgumentException("Unsupported sample rate: " + sampleRate);
        }
    }

    private static int findAvailablePort() throws IOException {
        try (ServerSocket socket = new ServerSocket(0)) {
            return socket.getLocalPort();
        }
    }

    private static void assertTrue(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }

    private static void assertEquals(int expected, int actual, String message) {
        if (expected != actual) {
            throw new AssertionError(message + ": expected " + expected + ", got " + actual);
        }
    }

    private static void assertEquals(String expected, String actual, String message) {
        if (!expected.equals(actual)) {
            throw new AssertionError(message + ": expected " + expected + ", got " + actual);
        }
    }

    private static void assertNear(double expected, double actual, double tolerance, String message) {
        if (Math.abs(expected - actual) > tolerance) {
            throw new AssertionError(message + ": expected " + expected + ", got " + actual);
        }
    }
}
