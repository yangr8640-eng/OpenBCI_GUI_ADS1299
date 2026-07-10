public class DataWriterAuxODF extends DataWriterODF {
    protected String fileNamePrependString = "OpenBCI-RAW-Aux-";
    protected String headerFirstLineString = "%OpenBCI Raw Aux Data";

    // Standard constructor: uses "OpenBCI-RAW-Aux-<fileName>.txt" pattern
    DataWriterAuxODF(String _sessionName, String _fileName) {
        super(_sessionName, _fileName);
    }

    // Extended constructor: when useAsCompleteName is true, _fileName is the complete name
    DataWriterAuxODF(String _sessionName, String _fileName, boolean useAsCompleteName) {
        super(_sessionName, _fileName, useAsCompleteName);
    }
    
    protected int getNumberOfChannels() {
        return ((AuxDataBoard)currentBoard).getNumAuxChannels();
    }

    protected int getSamplingRate() {
        return ((AuxDataBoard)currentBoard).getAuxSampleRate();
    }

    protected String getUnderlyingBoardClass() {
        return ((AuxDataBoard)currentBoard).getClass().getName();
    }

    protected String[] getChannelNames() {
        return ((AuxDataBoard)currentBoard).getAuxChannelNames();
    }

    protected int getTimestampChannel() {
        return ((AuxDataBoard)currentBoard).getAuxTimestampChannel();
    }

};
