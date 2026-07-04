import java.io.IOException;
import java.io.InputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;

import org.apache.commons.lang3.tuple.Pair;
import org.apache.commons.lang3.tuple.ImmutablePair;

class BoardADS129xTcp extends Board {
    private static final int NUM_EXG_CHANNELS = 16;
    private static final int TOTAL_CHANNELS = 21;
    private static final int SAMPLE_INDEX_CHANNEL = 0;
    private static final int EXG_START_CHANNEL = 1;
    private static final int BATTERY_CHANNEL = 17;
    private static final int LEAD_STATUS_CHANNEL = 18;
    private static final int TIMESTAMP_CHANNEL = 19;
    private static final int MARKER_CHANNEL = 20;

    private static final int READ_BUFFER_SIZE = 4096;
    private static final double ADS1299_LSB_UV = 4500000.0 / ((1 << 23) - 1);
    private static final double ADS1298_LSB_UV = 2400000.0 / ((1 << 23) - 1);

    private final int listenPort;
    private final int sampleRate;
    private final int[] exgChannels = new int[NUM_EXG_CHANNELS];
    private final boolean[] activeChannels = new boolean[NUM_EXG_CHANNELS];
    private final ConcurrentLinkedQueue<double[]> sampleQueue = new ConcurrentLinkedQueue<double[]>();
    private final ConcurrentLinkedQueue<String> warningQueue = new ConcurrentLinkedQueue<String>();
    private final ADS129xTcpParser parser = new ADS129xTcpParser();

    private volatile boolean shouldRun = false;
    private volatile boolean streaming = false;
    private volatile boolean connected = false;
    private volatile double pendingMarker = 0.0;

    private ServerSocket serverSocket = null;
    private Socket clientSocket = null;
    private Thread serverThread = null;
    private long outputSampleCounter = 0;
    private double firstTimestamp = -1.0;
    private Long lastFrameSequence = null;
    private long droppedFrames = 0;
    private boolean sampleRateMismatchWarned = false;
    private boolean channelCountWarned = false;
    private boolean queueOverflowWarned = false;

    BoardADS129xTcp(int listenPort, int sampleRate) {
        this.listenPort = listenPort;
        this.sampleRate = isSupportedSampleRate(sampleRate) ? sampleRate : 250;
        for (int i = 0; i < NUM_EXG_CHANNELS; i++) {
            exgChannels[i] = EXG_START_CHANNEL + i;
            activeChannels[i] = true;
        }
    }

    @Override
    protected boolean initializeInternal() {
        if (listenPort <= 0 || listenPort > 65535) {
            outputError("ADS1299: Invalid TCP listen port " + listenPort + ".");
            return false;
        }
        try {
            serverSocket = new ServerSocket(listenPort);
            shouldRun = true;
            serverThread = new Thread(new Runnable() {
                public void run() {
                    runServerLoop();
                }
            }, "ADS1299 TCP Server");
            serverThread.setDaemon(true);
            serverThread.start();
            println("ADS1299: Listening for TCP client on 0.0.0.0:" + listenPort);
            outputInfo("ADS1299: listening on TCP port " + listenPort + ". Configure the board with AT+PORT=" + listenPort + ".");
            return true;
        } catch (IOException e) {
            outputError("ADS1299: Could not listen on TCP port " + listenPort + ". Check whether another program is using it.");
            e.printStackTrace();
            return false;
        }
    }

    @Override
    protected void uninitializeInternal() {
        shouldRun = false;
        closeClientSocket();
        closeServerSocket();
        if (serverThread != null) {
            try {
                serverThread.join(500);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            serverThread = null;
        }
        sampleQueue.clear();
        connected = false;
    }

    @Override
    public void startStreaming() {
        super.startStreaming();
        sampleQueue.clear();
        warningQueue.clear();
        synchronized(parser) {
            parser.reset();
        }
        outputSampleCounter = 0;
        firstTimestamp = System.currentTimeMillis() / 1000.0;
        lastFrameSequence = null;
        droppedFrames = 0;
        sampleRateMismatchWarned = false;
        channelCountWarned = false;
        queueOverflowWarned = false;
        streaming = true;
        output("ADS1299 data stream started. Waiting for board TCP data on port " + listenPort + ".");
    }

    @Override
    public void stopStreaming() {
        super.stopStreaming();
        streaming = false;
        sampleQueue.clear();
    }

    @Override
    protected void updateInternal() {
        String message = warningQueue.poll();
        int displayed = 0;
        while (message != null && displayed < 3) {
            outputWarn(message);
            println("ADS1299: " + message);
            displayed++;
            message = warningQueue.poll();
        }
    }

    @Override
    protected double[][] getNewDataInternal() {
        List<double[]> samples = new ArrayList<double[]>();
        double[] row = sampleQueue.poll();
        while (row != null) {
            samples.add(row);
            row = sampleQueue.poll();
        }

        if (samples.size() == 0) {
            return emptyData;
        }

        double[][] data = new double[TOTAL_CHANNELS][samples.size()];
        for (int i = 0; i < samples.size(); i++) {
            double[] sample = samples.get(i);
            for (int channel = 0; channel < TOTAL_CHANNELS; channel++) {
                data[channel][i] = sample[channel];
            }
            for (int exg = 0; exg < NUM_EXG_CHANNELS; exg++) {
                if (!activeChannels[exg]) {
                    data[EXG_START_CHANNEL + exg][i] = 0.0;
                }
            }
        }
        return data;
    }

    @Override
    public boolean isConnected() {
        return serverSocket != null && !serverSocket.isClosed();
    }

    @Override
    public boolean isStreaming() {
        return streaming;
    }

    @Override
    public Pair<Boolean, String> sendCommand(String command) {
        return new ImmutablePair<Boolean, String>(Boolean.valueOf(false), "ADS1299 TCP board does not support GUI commands.");
    }

    public void insertMarker(int value) {
        insertMarker((double)value);
    }

    public void insertMarker(double value) {
        pendingMarker = value;
    }

    @Override
    public int getSampleRate() {
        return sampleRate;
    }

    @Override
    public void setEXGChannelActive(int channelIndex, boolean active) {
        if (channelIndex >= 0 && channelIndex < activeChannels.length) {
            activeChannels[channelIndex] = active;
        }
    }

    @Override
    public boolean isEXGChannelActive(int channelIndex) {
        if (channelIndex >= 0 && channelIndex < activeChannels.length) {
            return activeChannels[channelIndex];
        }
        return false;
    }

    @Override
    public int[] getEXGChannels() {
        return exgChannels;
    }

    @Override
    public int getTimestampChannel() {
        return TIMESTAMP_CHANNEL;
    }

    @Override
    public int getSampleIndexChannel() {
        return SAMPLE_INDEX_CHANNEL;
    }

    @Override
    public int getTotalChannelCount() {
        return TOTAL_CHANNELS;
    }

    public int getMarkerChannel() {
        return MARKER_CHANNEL;
    }

    @Override
    protected void addChannelNamesInternal(String[] channelNames) {
        channelNames[SAMPLE_INDEX_CHANNEL] = "Sample Index";
        for (int i = 0; i < NUM_EXG_CHANNELS; i++) {
            channelNames[EXG_START_CHANNEL + i] = "ADS1299 Ch " + (i + 1);
        }
        channelNames[BATTERY_CHANNEL] = "Battery";
        channelNames[LEAD_STATUS_CHANNEL] = "Lead Status";
        channelNames[TIMESTAMP_CHANNEL] = "Timestamp";
        channelNames[MARKER_CHANNEL] = "Marker";
    }

    @Override
    protected PacketLossTracker setupPacketLossTracker() {
        final int minSampleIndex = 0;
        final int maxSampleIndex = 255;
        PacketLossTracker tracker = new PacketLossTracker(getSampleIndexChannel(), getTimestampChannel(),
                                                         minSampleIndex, maxSampleIndex);
        tracker.silent = true;
        return tracker;
    }

    private void runServerLoop() {
        while (shouldRun) {
            try {
                Socket socket = serverSocket.accept();
                clientSocket = socket;
                connected = true;
                println("ADS1299: TCP client connected from " + socket.getInetAddress().getHostAddress() + ":" + socket.getPort());
                warningQueue.add("ADS1299 board connected from " + socket.getInetAddress().getHostAddress() + ".");
                readClient(socket);
            } catch (SocketException e) {
                if (shouldRun) {
                    warningQueue.add("ADS1299 TCP server socket error: " + e.getMessage());
                    e.printStackTrace();
                }
            } catch (IOException e) {
                if (shouldRun) {
                    warningQueue.add("ADS1299 TCP server error: " + e.getMessage());
                    e.printStackTrace();
                }
            } finally {
                connected = false;
                closeClientSocket();
            }
        }
    }

    private void readClient(Socket socket) throws IOException {
        InputStream input = socket.getInputStream();
        byte[] readBuffer = new byte[READ_BUFFER_SIZE];
        while (shouldRun && !socket.isClosed()) {
            int read = input.read(readBuffer);
            if (read < 0) {
                warningQueue.add("ADS1299 board disconnected. Waiting for reconnect.");
                return;
            }
            if (read > 0) {
                List<ADS129xTcpFrame> frames;
                synchronized(parser) {
                    frames = parser.feed(readBuffer, read);
                }
                for (int i = 0; i < frames.size(); i++) {
                    handleFrame(frames.get(i));
                }
            }
        }
    }

    private void handleFrame(ADS129xTcpFrame frame) {
        if (!streaming) {
            return;
        }
        if (!frame.isEegFrame()) {
            return;
        }
        if (frame.channelCount != NUM_EXG_CHANNELS) {
            if (!channelCountWarned) {
                warningQueue.add("ADS1299 frame has " + frame.channelCount + " channels; expected 16. Frame ignored.");
                channelCountWarned = true;
            }
            return;
        }
        if (frame.sampleRate > 0 && frame.sampleRate != sampleRate && !sampleRateMismatchWarned) {
            warningQueue.add("ADS1299 frame sample rate is " + frame.sampleRate + " Hz, but GUI is set to " + sampleRate + " Hz. Stop session and choose the correct sample rate.");
            sampleRateMismatchWarned = true;
        }

        trackFrameSequence(frame.sequence);

        for (int i = 0; i < frame.rawSamples.size(); i++) {
            int[] rawSample = frame.rawSamples.get(i);
            double[] row = new double[TOTAL_CHANNELS];
            row[SAMPLE_INDEX_CHANNEL] = outputSampleCounter % 256;
            for (int ch = 0; ch < NUM_EXG_CHANNELS; ch++) {
                row[EXG_START_CHANNEL + ch] = adcToUv(rawSample[ch], frame.chipTypeCode, frame.gain);
            }
            row[BATTERY_CHANNEL] = frame.battery;
            row[LEAD_STATUS_CHANNEL] = frame.leadStatus;
            row[TIMESTAMP_CHANNEL] = firstTimestamp + (outputSampleCounter / (double)sampleRate);
            row[MARKER_CHANNEL] = pendingMarker;
            pendingMarker = 0.0;
            sampleQueue.add(row);
            outputSampleCounter++;
            trimQueueIfNeeded();
        }
    }

    private void trackFrameSequence(long sequence) {
        if (lastFrameSequence != null) {
            long expected = lastFrameSequence.longValue() + 1L;
            if (sequence > expected) {
                long gap = sequence - expected;
                droppedFrames += gap;
                warningQueue.add("ADS1299 sequence gap detected: lost " + gap + " frame(s), total " + droppedFrames + ".");
            }
        }
        lastFrameSequence = Long.valueOf(sequence);
    }

    private void trimQueueIfNeeded() {
        int maxQueuedSamples = max(sampleRate * 10, sampleRate);
        if (sampleQueue.size() > maxQueuedSamples) {
            while (sampleQueue.size() > maxQueuedSamples) {
                sampleQueue.poll();
            }
            if (!queueOverflowWarned) {
                warningQueue.add("ADS1299 sample queue overflow; old samples were dropped.");
                queueOverflowWarned = true;
            }
        }
    }

    private double adcToUv(int raw, int chipTypeCode, int gain) {
        double lsbUv = (chipTypeCode == 0) ? ADS1299_LSB_UV : ADS1298_LSB_UV;
        int safeGain = (gain > 0) ? gain : 1;
        return raw * lsbUv / safeGain;
    }

    private boolean isSupportedSampleRate(int rate) {
        return rate == 250 || rate == 500 || rate == 1000;
    }

    private void closeServerSocket() {
        if (serverSocket != null) {
            try {
                serverSocket.close();
            } catch (IOException e) {
                e.printStackTrace();
            }
            serverSocket = null;
        }
    }

    private void closeClientSocket() {
        if (clientSocket != null) {
            try {
                clientSocket.close();
            } catch (IOException e) {
                e.printStackTrace();
            }
            clientSocket = null;
        }
    }
}

class ADS129xTcpFrame {
    int function;
    long sequence;
    int chipTypeCode;
    int channelCount;
    int battery;
    int sampleRate;
    int gain;
    int leadStatus;
    List<int[]> rawSamples;

    ADS129xTcpFrame(int function, long sequence, int chipTypeCode, int channelCount,
                    int battery, int sampleRate, int gain, int leadStatus, List<int[]> rawSamples) {
        this.function = function;
        this.sequence = sequence;
        this.chipTypeCode = chipTypeCode;
        this.channelCount = channelCount;
        this.battery = battery;
        this.sampleRate = sampleRate;
        this.gain = gain;
        this.leadStatus = leadStatus;
        this.rawSamples = rawSamples;
    }

    boolean isEegFrame() {
        return function == 0x05 && rawSamples.size() > 0;
    }
}

class ADS129xTcpParser {
    private static final int MAX_BUFFER_SIZE = 131072;
    private byte[] buffer = new byte[8192];
    private int bufferLength = 0;

    void reset() {
        bufferLength = 0;
    }

    List<ADS129xTcpFrame> feed(byte[] data, int length) {
        append(data, length);
        List<ADS129xTcpFrame> frames = new ArrayList<ADS129xTcpFrame>();

        while (true) {
            int start = findFrameHead();
            if (start < 0) {
                keepPossibleHeadByte();
                break;
            }
            if (start > 0) {
                discard(start);
            }
            if (bufferLength < 16) {
                break;
            }

            int dataLength = readUInt16(14);
            int totalLength = 16 + dataLength + 2 + 2;
            if (totalLength > MAX_BUFFER_SIZE) {
                discard(1);
                continue;
            }
            if (bufferLength < totalLength) {
                break;
            }
            if (u(16 + dataLength + 2) != 0x5A || u(16 + dataLength + 3) != 0x5A) {
                discard(1);
                continue;
            }
            int expectedChecksum = readUInt16(16 + dataLength);
            int actualChecksum = 0;
            for (int i = 0; i < 16 + dataLength; i++) {
                actualChecksum = (actualChecksum + u(i)) & 0xFFFF;
            }
            if (expectedChecksum != actualChecksum) {
                discard(totalLength);
                continue;
            }

            ADS129xTcpFrame frame = parseFrame(dataLength);
            if (frame != null) {
                frames.add(frame);
            }
            discard(totalLength);
        }

        return frames;
    }

    private ADS129xTcpFrame parseFrame(int dataLength) {
        int function = u(3);
        int channelByte = u(8);
        int chipTypeCode = (channelByte >> 6) & 0x03;
        int channelCount = channelCountFromMask(channelByte & 0x3F);
        int sampleRateGain = u(11);
        int sampleRate = sampleRateFromCode((sampleRateGain >> 4) & 0x0F);
        int gain = gainFromCode(sampleRateGain & 0x0F);
        int leadStatus = readUInt16(12);
        List<int[]> rawSamples = new ArrayList<int[]>();

        if (function == 0x05 && channelCount > 0) {
            int sampleWidth = 3 * channelCount;
            if (dataLength % sampleWidth != 0) {
                return null;
            }
            for (int offset = 0; offset < dataLength; offset += sampleWidth) {
                int[] sample = new int[channelCount];
                for (int ch = 0; ch < channelCount; ch++) {
                    sample[ch] = readInt24(16 + offset + ch * 3);
                }
                rawSamples.add(sample);
            }
        }

        return new ADS129xTcpFrame(
            function,
            readUInt32(4),
            chipTypeCode,
            channelCount,
            u(10),
            sampleRate,
            gain,
            leadStatus,
            rawSamples
        );
    }

    private void append(byte[] data, int length) {
        ensureCapacity(bufferLength + length);
        System.arraycopy(data, 0, buffer, bufferLength, length);
        bufferLength += length;
    }

    private void ensureCapacity(int capacity) {
        if (capacity <= buffer.length) {
            return;
        }
        int newLength = buffer.length;
        while (newLength < capacity) {
            newLength *= 2;
        }
        byte[] newBuffer = new byte[newLength];
        System.arraycopy(buffer, 0, newBuffer, 0, bufferLength);
        buffer = newBuffer;
    }

    private int findFrameHead() {
        for (int i = 0; i < bufferLength - 1; i++) {
            if (u(i) == 0xA5 && u(i + 1) == 0xA5) {
                return i;
            }
        }
        return -1;
    }

    private void keepPossibleHeadByte() {
        if (bufferLength > 0 && u(bufferLength - 1) == 0xA5) {
            buffer[0] = buffer[bufferLength - 1];
            bufferLength = 1;
        } else {
            bufferLength = 0;
        }
    }

    private void discard(int count) {
        if (count <= 0) {
            return;
        }
        if (count >= bufferLength) {
            bufferLength = 0;
            return;
        }
        System.arraycopy(buffer, count, buffer, 0, bufferLength - count);
        bufferLength -= count;
    }

    private int u(int index) {
        return buffer[index] & 0xFF;
    }

    private int readUInt16(int offset) {
        return (u(offset) << 8) | u(offset + 1);
    }

    private long readUInt32(int offset) {
        return ((long)u(offset) << 24)
             | ((long)u(offset + 1) << 16)
             | ((long)u(offset + 2) << 8)
             | (long)u(offset + 3);
    }

    private int readInt24(int offset) {
        int value = (u(offset) << 16) | (u(offset + 1) << 8) | u(offset + 2);
        if ((value & 0x800000) != 0) {
            value -= 0x1000000;
        }
        return value;
    }

    private int channelCountFromMask(int mask) {
        switch (mask) {
            case 0x20:
                return 32;
            case 0x10:
                return 16;
            case 0x08:
                return 8;
            case 0x04:
                return 4;
            case 0x02:
                return 2;
            case 0x01:
                return 1;
            default:
                return mask;
        }
    }

    private int sampleRateFromCode(int code) {
        switch (code) {
            case 0:
                return 32000;
            case 1:
                return 16000;
            case 2:
                return 8000;
            case 3:
                return 4000;
            case 4:
                return 2000;
            case 5:
                return 1000;
            case 6:
                return 500;
            case 7:
                return 250;
            default:
                return -1;
        }
    }

    private int gainFromCode(int code) {
        switch (code) {
            case 0:
                return 24;
            case 1:
                return 12;
            case 2:
                return 8;
            case 3:
                return 6;
            case 4:
                return 4;
            case 5:
                return 3;
            case 6:
                return 2;
            case 7:
                return 1;
            default:
                return 1;
        }
    }
}
