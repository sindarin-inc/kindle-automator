// Configure noVNC settings for embedding in mobile apps
// This file should be copied to /opt/novnc/app/

// Set default connection parameters
var CONFIG = {
    // VNC connection settings
    path: 'websockify',
    encrypt: false,
    repeaterID: '',
    shared: true,
    showDotCursor: true,
    autoconnect: true,
    
    // UI settings for embedded mode
    view_only: false,  // Allow interaction by default
    resize: 'scale',   // Scale to fit
    quality: 6,        // Medium quality (1-9)
    compression: 2,    // Medium compression (0-9)
    reconnect: true,   // Automatically reconnect
    reconnect_delay: 5000,
    
    // Mobile-specific settings
    virtual_keyboard_visible: true,  // Show virtual keyboard on mobile
    webgl: true,                    // Use WebGL rendering for better performance
    
    // Performance settings
    fps: 30,              // Target 30 FPS for smooth interaction
    treat_lossless: true, // Use lossless encoding when possible
};