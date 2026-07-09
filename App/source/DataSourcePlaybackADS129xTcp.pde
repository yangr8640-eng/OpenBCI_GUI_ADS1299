class DataSourcePlaybackADS129xTcp extends DataSourcePlayback implements FileBoard  {
   
    DataSourcePlaybackADS129xTcp(String filePath) {
        super(filePath);
    }

    @Override
    protected boolean instantiateUnderlyingBoard() {
        try {
            underlyingBoard = new BoardADS129xTcp(0, getSampleRate()) {
                @Override
                protected boolean initializeInternal() {
                    return true;
                }

                @Override
                protected void uninitializeInternal() {
                    // No-op for playback-only mode.
                }
            };
        } catch (Exception e) {
            println(e.getMessage());
            e.printStackTrace();
            return false;
        }

        return underlyingBoard != null;
    }
}
