# README.md - SpeechToText

## Overview

SpeechToText is a Python application that records audio from a microphone and transcribes it to text using Azure Speech-to-Text services. The transcribed text is copied to the clipboard and pasted into the active application. It runs in the system tray for easy access.

## Installation

1. **Install Dependencies**:
   Open a terminal and run:
   ```bash
   pip install pynput sounddevice requests pyperclip pystray keyboard soundfile simpleaudio python-dotenv
   ```

2. **Set Azure API Details**:
   Create a [`.env`](.env ) file in the same directory as the script with your Azure Speech-to-Text credentials:
   ```plaintext
   AZURE_ENDPOINT=your_azure_endpoint
   AZURE_API_KEY=your_azure_api_key
   ```

3. **Provide Sound Files**:
   Add short WAV files for feedback sounds ([`start.wav`](start.wav ), [`stop.wav`](stop.wav ), [`cancel.wav`](cancel.wav )) in the same directory as the script.

4. **Run the App**:
   In the terminal, execute:
   ```bash
   python speechtotext.py
   ```

## Usage

- The application runs in the system tray.
- Press **Ctrl + Windows key** to start recording.
- Release or press **Ctrl + Windows key** again to stop recording and transcribe the audio.
- Press **Esc** during recording to cancel.
- Right-click the tray icon to select a microphone or exit the application.

## Building an Executable

To create a standalone executable, use PyInstaller with the following command:
```bash
pyinstaller --noconfirm --onefile --windowed --icon=speaking.ico --add-data "start.wav;." --add-data "stop.wav;." --add-data "cancel.wav;." --add-data "speaking.ico;." speechtotext.py
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.