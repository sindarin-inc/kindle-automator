## Installation Instructions

To get started with the automation setup, you need to install Appium and the necessary drivers. Follow the steps below:

1. **Install Appium**:
   Appium is a tool for automating mobile applications. You can install it using npm (Node Package Manager). If you don't have npm installed, you need to install Node.js first, which includes npm.

   ```sh
   npm install -g appium
   ```

2. **Install UiAutomator2 Driver**:
   After installing Appium, you need to install the UiAutomator2 driver, which is required for Android automation.

   ```sh
   appium driver install uiautomator2
   ```

3. **Verify Installation**:
   To verify that Appium and the UiAutomator2 driver are installed correctly, you can run the following command:

   ```sh
   appium -v
   ```

   This should display the version of Appium installed. Additionally, you can check the installed drivers by running:

   ```sh
   appium driver list
   ```

   This should list `uiautomator2` among the installed drivers.

Now you are ready to proceed with the automation setup and run the scripts.

4. **Install Android Studio**:
   To run Android emulators and use Android SDK tools, you need to install Android Studio. Follow the steps below to install Android Studio:

   - Download Android Studio from the official website: https://developer.android.com/studio
   - Follow the installation instructions for your operating system (Windows, macOS, or Linux).
   - During the installation, make sure to install the Android SDK and Android Virtual Device (AVD) components.

5. **Set Up Android SDK**:
   After installing Android Studio, you need to set up the Android SDK and ensure that the `adb` (Android Debug Bridge) tool is available in your system's PATH.

   - Open Android Studio and go to `Preferences` (macOS) or `Settings` (Windows/Linux).
   - Navigate to `Appearance & Behavior` > `System Settings` > `Android SDK`.
   - Make sure the SDK Path is set to the default location or a location of your choice.
   - Under the `SDK Tools` tab, ensure that the following tools are installed:
     - Android SDK Build-Tools
     - Android Emulator
     - Android SDK Platform-Tools
     - Android SDK Tools

6. **Add Android SDK to PATH**:
   To use `adb` and other Android SDK tools from the command line, you need to add the Android SDK's `platform-tools` directory to your system's PATH.

   - For macOS/Linux:

     ```sh
     echo 'export ANDROID_HOME=~/Library/Android/sdk' >> ~/.bash_profile
     echo 'export PATH=$PATH:$ANDROID_HOME/platform-tools' >> ~/.bash_profile
     source ~/.bash_profile
     ```

   - For Windows:
     - Open `System Properties` (right-click on `This PC` or `My Computer` and select `Properties`).
     - Click on `Advanced system settings` and then `Environment Variables`.
     - Under `System variables`, find the `Path` variable, select it, and click `Edit`.
     - Add the path to the `platform-tools` directory (e.g., `C:\Users\<YourUsername>\AppData\Local\Android\Sdk\platform-tools`).

7. **Verify Android SDK Installation**:
   To verify that the Android SDK is installed correctly and `adb` is available, you can run the following command:

   ```sh
   adb devices
   ```

   This should list any connected Android devices or running emulators. If no devices are listed, ensure that your device is connected and USB debugging is enabled, or that an emulator is running.

Now you are ready to proceed with the automation setup and run the scripts.

8. **Set Up Virtual Environment**:
   To ensure that all dependencies are installed in an isolated environment, you should set up a virtual environment using `virtualenv`.

   - Install `virtualenv` if you haven't already:

     ```sh
     uv install virtualenv
     ```

   - Create a virtual environment named `kindle-automator`:

     ```sh
     virtualenv kindle-automator
     ```

   - Activate the virtual environment:
     - For macOS/Linux:
       ```sh
       source kindle-automator/bin/activate
       ```
     - For Windows:
       ```sh
       .\kindle-automator\Scripts\activate
       ```

9. **Install Dependencies**:
   Once the virtual environment is activated, install the required dependencies using `make deps`:

   ```sh
   make deps
   ```

10. **Run the Script**:
    After setting up the virtual environment and installing dependencies, you can run the automation script using:

    ```sh
    make run
    ```

    This will install the Kindle APK and start the Flask server so it's ready to automate the app.

## Important files

- `server/server.py`: Flask server on port 4098
- `views/state_machine.py`: Handles Kindle app states and transitions
- `views/core/app_state.py`: Kindle views and app states
- `views/transition.py`: Controller between states and handlers
- `views/view_inspector.py`: App view identifying, interacting with appium driver
- `handlers/*_handler.py`: Various handlers for different app states
- `automator.py`: Glue between the Kindle side and the server side, ensuring driver is running
- `driver.py`: Handles Appium driver initialization and management
