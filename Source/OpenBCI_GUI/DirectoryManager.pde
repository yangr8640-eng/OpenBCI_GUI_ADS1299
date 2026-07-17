class DirectoryManager {

    private final String guiDataPath;
    private final String recordingsPath;
    private final String settingsPath;
    private final String consoleDataPath;
    private final DateFormat dateFormat = new SimpleDateFormat("yyyy-MM-dd_HH-mm-ss");

    DirectoryManager() {
        String configuredPath = System.getenv("OPENBCI_GUI_DATA_DIR");

        if (configuredPath == null || configuredPath.trim().isEmpty()) {
            File legacyDataDirectory = new File(
                "D:" + File.separator + "OpenBCI_GUI_ADS1299" + File.separator + "UserData"
            );
            if (legacyDataDirectory.isDirectory()) {
                configuredPath = legacyDataDirectory.getAbsolutePath();
            } else {
                String localAppData = System.getenv("LOCALAPPDATA");
                if (localAppData == null || localAppData.trim().isEmpty()) {
                    localAppData = System.getProperty("user.home");
                }

                configuredPath = new File(
                    localAppData,
                    "OpenBCI_GUI_ADS1299" + File.separator + "UserData"
                ).getAbsolutePath();
            }
        }

        guiDataPath = new File(configuredPath).getAbsolutePath() + File.separator;
        recordingsPath = guiDataPath + "Recordings" + File.separator;
        settingsPath = guiDataPath + "Settings" + File.separator;
        consoleDataPath = guiDataPath + "Console_Data" + File.separator;
    }

    public String getFileNameDateTime() {
        return dateFormat.format(new Date());
    }
    
    public String getGuiDataPath() {
        return guiDataPath;
    }

    public String getRecordingsPath() {
        return recordingsPath;
    }

    public String getSettingsPath() {
        return settingsPath;
    }

    public String getConsoleDataPath() {
        return consoleDataPath;
    }

    public boolean init() {
        String directoryName = guiDataPath + "Sample_Data" + File.separator;
        File directory = new File(directoryName);
        File[] requiredDirectories = {
            new File(guiDataPath),
            new File(recordingsPath),
            new File(settingsPath),
            new File(consoleDataPath),
            directory
        };

        for (File requiredDirectory : requiredDirectories) {
            if (!ensureDirectory(requiredDirectory)) {
                println("OpenBCI_GUI::Setup: Unable to create data directory: " + requiredDirectory.getAbsolutePath());
                return false;
            }
        }

        String guiv4fileName = directoryName + "OpenBCI-sampleData-2-meditation.txt";
        String guiv5fileName = directoryName + "OpenBCI_GUI-v5-meditation.txt";
        File guiv4_fileToCheck = new File(guiv4fileName);
        File guiv5_fileToCheck = new File(guiv5fileName);

        if (guiv4_fileToCheck.exists()) {
            //Delete old gui v4 files in Documents folder
            try {
                for (File subFile : directory.listFiles()) {
                    subFile.delete();
                }
                println("OpenBCI_GUI::Setup: Successfully deleted old GUI v4 sample data files!");
            } catch (SecurityException e) {
                println("OpenBCI_GUI::Setup: Error trying to delete old GUI Sample Data.");
            }
        }
        
        if (!guiv5_fileToCheck.exists()) {
            copySampleDataFiles(directory, directoryName);
        } else {
            println("OpenBCI_GUI::Setup: GUI v5 Sample Data exists.");
        }

        return true;
    }

    private void copySampleDataFiles(File directory, String directoryName) {
        println("OpenBCI_GUI::Setup: Copying sample data to " + guiDataPath + "Sample_Data");
        try {
            File[] filesFound = new File(dataPath("EEG_Sample_Data")).listFiles();
            if (filesFound == null) {
                println("OpenBCI_GUI::Setup: Bundled sample data directory is missing or inaccessible.");
                return;
            }

            for (File file : filesFound) {
                if (file.isFile()) {
                    Files.copy(file.toPath(),
                        (new File(directoryName + file.getName())).toPath(),
                        StandardCopyOption.REPLACE_EXISTING);
                }
            }
        } catch (IOException e) {
            println("OpenBCI_GUI::Setup: Error trying to copy Sample Data to GUI data directory.");
        }
    }

    private boolean ensureDirectory(File directory) {
        return directory.isDirectory() || directory.mkdirs() || directory.isDirectory();
    }
    
};
