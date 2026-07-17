import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * Lightweight TCP server that accepts remote commands to control data recording.
 *
 * Use case: the MIST EEG experiment (Python/PsychoPy) sends commands at stage
 * boundaries so the GUI automatically starts/stops recording with the correct
 * file name without manual intervention.
 *
 * Protocol (newline-delimited text):
 *   RECORD:<name>  – stop current recording, set file name, start new recording
 *   STOP           – stop current recording
 *   PING           – respond "PONG" (connection test)
 *
 * Thread safety: network I/O runs on a daemon thread; commands are queued and
 * dispatched on the main draw/update thread via checkCommands().
 */
class ExperimentControlServer {
    private final int listenPort;
    private volatile boolean shouldRun = false;
    private ServerSocket serverSocket = null;
    private Socket clientSocket = null;
    private Thread serverThread = null;
    private PrintWriter clientOut = null;
    private final ConcurrentLinkedQueue<String> commandQueue = new ConcurrentLinkedQueue<String>();

    ExperimentControlServer(int port) {
        listenPort = port;
    }

    // ---- Lifecycle ----

    public void start() {
        if (listenPort <= 0 || listenPort > 65535) {
            println("ExpCtrlServer: Invalid port " + listenPort + ". Not starting.");
            return;
        }
        try {
            // Control is deliberately loopback-only; participant/file names must
            // never be controllable by another machine on the LAN.
            serverSocket = new ServerSocket();
            serverSocket.setReuseAddress(true);
            serverSocket.bind(new InetSocketAddress(InetAddress.getLoopbackAddress(), listenPort));
            shouldRun = true;
            serverThread = new Thread(new Runnable() {
                public void run() {
                    runServerLoop();
                }
            }, "ExperimentControlServer");
            serverThread.setDaemon(true);
            serverThread.start();
            println("ExpCtrlServer: Listening for experiment control commands on 127.0.0.1:" + listenPort);
        } catch (IOException e) {
            println("ExpCtrlServer: Could not listen on port " + listenPort + ": " + e.getMessage());
        }
    }

    public void stop() {
        shouldRun = false;
        closeClient();
        closeServerSocket();
        if (serverThread != null) {
            try {
                serverThread.join(500);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            serverThread = null;
        }
        commandQueue.clear();
        println("ExpCtrlServer: Stopped.");
    }

    // ---- Server loop (daemon thread) ----

    private void runServerLoop() {
        while (shouldRun) {
            try {
                if (serverSocket == null || serverSocket.isClosed()) break;
                println("ExpCtrlServer: Waiting for client connection...");
                clientSocket = serverSocket.accept();
                clientSocket.setTcpNoDelay(true);
                clientSocket.setSoTimeout(0); // block indefinitely
                clientOut = new PrintWriter(clientSocket.getOutputStream(), true);
                println("ExpCtrlServer: Client connected: " + clientSocket.getInetAddress());

                BufferedReader reader = new BufferedReader(
                    new InputStreamReader(clientSocket.getInputStream(), "UTF-8"));
                String line;
                while (shouldRun && (line = reader.readLine()) != null) {
                    line = line.trim();
                    if (!line.isEmpty()) {
                        commandQueue.add(line);
                        println("ExpCtrlServer: Queued command: " + line);
                    }
                }
            } catch (IOException e) {
                if (shouldRun) {
                    println("ExpCtrlServer: Connection error: " + e.getMessage());
                }
            } finally {
                closeClient();
            }
        }
    }

    // ---- Called from the main draw thread ----

    /**
     * Drain the command queue and dispatch each command on the main thread.
     * Must be called from the Processing draw() / systemUpdate() thread because
     * most GUI operations (startRunning, stopRunning, DataLogger, etc.) are not
     * thread-safe.
     */
    public void checkCommands() {
        String cmd;
        while ((cmd = commandQueue.poll()) != null) {
            dispatchCommand(cmd);
        }
    }

    // ---- Command dispatch ----

    private void dispatchCommand(String cmd) {
        if (cmd.equalsIgnoreCase("PING")) {
            sendResponse("PONG");
            println("ExpCtrlServer: PING received, sent PONG");
        } else if (cmd.equalsIgnoreCase("STATUS")) {
            sendResponse(experimentControlGetStatus());
        } else if (cmd.equalsIgnoreCase("STOP")) {
            println("ExpCtrlServer: Executing STOP");
            sendResponse(experimentControlStopRecording());
        } else if (cmd.toUpperCase().startsWith("RECORD:")) {
            String payload = cmd.substring(7).trim();
            if (payload.isEmpty()) {
                sendResponse("ERR:empty recording name");
                return;
            }
            String experimentSessionName = payload;
            String fileName = payload;
            int separator = payload.indexOf('|');
            if (separator >= 0) {
                experimentSessionName = payload.substring(0, separator).trim();
                fileName = payload.substring(separator + 1).trim();
            }
            experimentSessionName = sanitizeName(experimentSessionName);
            fileName = sanitizeName(fileName);
            if (experimentSessionName.isEmpty() || fileName.isEmpty()) {
                sendResponse("ERR:invalid recording name");
                return;
            }
            println("ExpCtrlServer: Executing RECORD '" + fileName + "'");
            sendResponse(experimentControlStartRecording(experimentSessionName, fileName));
        } else {
            sendResponse("ERR:unknown command: " + cmd);
            println("ExpCtrlServer: Unknown command: " + cmd);
        }
    }

    private String sanitizeName(String value) {
        String sanitized = value.replaceAll("[^A-Za-z0-9._-]", "_");
        if (sanitized.length() > 120) {
            sanitized = sanitized.substring(0, 120);
        }
        return sanitized;
    }

    private void sendResponse(String msg) {
        if (clientOut != null) {
            try {
                clientOut.println(msg);
                clientOut.flush();
            } catch (Exception e) {
                // client may have disconnected – ignore
            }
        }
    }

    // ---- Helpers for clean shutdown ----

    private void closeClient() {
        if (clientSocket != null) {
            try { clientSocket.close(); } catch (IOException e) { }
            clientSocket = null;
        }
        clientOut = null;
    }

    private void closeServerSocket() {
        if (serverSocket != null) {
            try { serverSocket.close(); } catch (IOException e) { }
            serverSocket = null;
        }
    }
}
