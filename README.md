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

10. **Configuration**:
    The application uses a `.env` file for API keys and other configuration. Create your `.env` file by copying the example:

    ```sh
    cp .env.example .env
    ```

    Then edit the `.env` file to add your API keys:

    ```
    # API Keys 
    MISTRAL_API_KEY=your-actual-mistral-api-key
    ```

    This file is listed in `.gitignore` to ensure your API keys are never committed to the repository.
    
    **Note**: Amazon credentials (email and password) must be provided in the /auth API request, and captcha solutions (if needed) must be provided to the /captcha endpoint. These are not read from environment variables or configuration files. The system will automatically initialize when needed, but you must authenticate with the /auth endpoint before accessing other features.

11. **Run the Script**:
    After setting up the virtual environment, installing dependencies, and configuring your environment, you can run the automation script using:

    ```sh
    make run
    ```

    This will install the Kindle APK and start the Flask server so it's ready to automate the app.

## User Profiles

The system now includes AVD profile management that creates and manages separate Android Virtual Devices for each user account. This allows you to:

- Maintain multiple authenticated Kindle accounts simultaneously
- Switch between accounts without having to re-authenticate each time
- Preserve the state of each account, including downloaded books and login credentials

Each time a new email address is sent to the `/auth` endpoint, the system automatically:
1. Checks if a profile already exists for this email
2. If it exists, switches to that profile
3. If not, creates a new AVD profile for the email
4. Initializes the Kindle app in the selected profile

### Profile Management API Endpoints

- `GET /profiles` - List all available profiles and the current active profile
- `POST /profiles` - Create, delete, or switch profiles with `action` parameter:
  - `{"action": "create", "email": "user@example.com"}`
  - `{"action": "delete", "email": "user@example.com"}`
  - `{"action": "switch", "email": "user@example.com"}`
- When using `/auth`, you can add a `recreate` parameter to delete and recreate a profile:
  - `{"email": "user@example.com", "password": "password123", "recreate": true}`
  - This is useful when you want to start fresh with a clean profile

### Using AVDs Created in Android Studio

For M1/M2/M4 Mac users who need to create and manage AVDs directly in Android Studio, we've added a special workflow:

1. Create your AVD in Android Studio with your preferred settings
2. Register the AVD with Kindle Automator using one of the following:
   ```bash
   # Interactive registration
   make register-avd
   
   # Complete workflow (recommended)
   make android-studio-avd
   ```
3. Start the emulator manually from Android Studio
4. Run the Kindle Automator server with:
   ```bash
   make server
   ```

This approach allows you to use manually created AVDs with the profile tracking system. The system will associate your Android Studio AVD with a specific email account and track which one is active, without trying to start the emulator itself.

### Special Notes for M1/M2/M4 Mac Users

Due to compatibility issues with Android emulation on ARM-based Macs, the profile system has been adapted to:

1. Create and track profiles without attempting to start the emulator automatically  
2. Provide several ways to manage the emulator:

#### Development Workflow Commands

- **Start both emulator and server together**:
  ```bash
  make dev
  ```
  This single command starts the emulator for the current profile and then launches the server.

- **Start just the emulator for the current profile**:
  ```bash
  make run-emulator
  ```
  This automatically selects the AVD associated with the current profile (e.g., after using `make profile-switch`).

- **Choose which AVD to start**:
  ```bash
  make run-emulator-choose
  ```
  This shows a list of all available AVDs and lets you select which one to run.

- **Register an Android Studio AVD**:
  ```bash
  make register-avd
  ```
  This allows you to associate an Android Studio AVD with an email profile.

#### Typical Development Workflow

1. Create or switch to a profile:
   ```bash
   make profile-create EMAIL=user@example.com
   ```
   or
   ```bash
   make profile-switch EMAIL=user@example.com
   ```

2. Start everything with one command:
   ```bash
   make dev
   ```

3. Test the API endpoints:
   ```bash
   make test-auth EMAIL=user@example.com PASSWORD=yourpassword
   ```

The system will track which profile is "current" even if the emulator starts separately.

#### Android Studio Workflow (for M4 Macs)

1. Create AVDs directly in Android Studio
2. Register them with Kindle Automator:
   ```bash
   make android-studio-avd
   ```
3. Start the emulator from Android Studio
4. Start the server:
   ```bash
   make server
   ```
5. Test the API endpoints:
   ```bash
   make test-auth EMAIL=user@example.com PASSWORD=yourpassword
   ```

In production environments (Linux servers), the emulator starts automatically as part of the profile switching process without needing manual intervention.

## Important files

- `server/server.py`: Flask server on port 4098
- `views/state_machine.py`: Handles Kindle app states and transitions
- `views/core/app_state.py`: Kindle views and app states
- `views/core/avd_profile_manager.py`: Manages AVD profiles for different user accounts
- `views/transition.py`: Controller between states and handlers
- `views/view_inspector.py`: App view identifying, interacting with appium driver
- `handlers/*_handler.py`: Various handlers for different app states
- `automator.py`: Glue between the Kindle side and the server side, ensuring driver is running
- `driver.py`: Handles Appium driver initialization and management

