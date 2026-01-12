#!/usr/bin/env python3
"""
Quick diagnostic script to test IMX258 focus motor functionality.
Tests if the motor responds to commands at all.
"""

import logging
import time
import hololink as hololink_module

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_focus_motor(camera_ip="192.168.0.2", camera_id=0):
    """Test if focus motor responds to commands."""
    
    logging.info("=" * 80)
    logging.info("IMX258 Focus Motor Diagnostic Test")
    logging.info("=" * 80)
    
    try:
        # Find device
        logging.info(f"Searching for Hololink device at {camera_ip}...")
        channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=camera_ip)
        if not channel_metadata:
            logging.error(f"Failed to find Hololink device at {camera_ip}")
            return False
        
        logging.info("Device found, initializing camera...")
        hololink_channel = hololink_module.DataChannel(channel_metadata)
        camera = hololink_module.sensors.imx258.Imx258(hololink_channel, camera_id)
        
        # Start Hololink (required for I2C communication)
        hololink = hololink_channel.hololink()
        hololink.start()
        logging.info("Hololink started successfully")
        
        # Configure camera (required before focus commands)
        camera_mode = hololink_module.sensors.imx258.Imx258_Mode(0)
        camera.configure(camera_mode)
        
        version = camera.get_version()
        logging.info(f"Camera version: {version}")
        
        # Test sequence: try different focus values with delays
        test_values = [0, -140, -200, -300, -400, -511, 511, 200, 100, 0]
        
        logging.info("\nStarting focus motor test sequence...")
        logging.info("Listen for clicking sounds from the camera during this test")
        logging.info("-" * 80)
        
        for i, focus_val in enumerate(test_values):
            logging.info(f"\nTest {i+1}/{len(test_values)}: Setting focus to {focus_val}")
            
            try:
                camera.set_focus(focus_val)
                logging.info(f"  ✓ Command sent successfully")
                
                # Give motor time to move
                time.sleep(1.0)
                
                # Prompt user
                response = input(f"  Did you hear a clicking sound? (y/n/q to quit): ").strip().lower()
                
                if response == 'q':
                    logging.info("Test aborted by user")
                    break
                elif response == 'y':
                    logging.info(f"  ✓ Motor responded at focus={focus_val}")
                else:
                    logging.info(f"  ✗ No motor response at focus={focus_val}")
                    
            except Exception as e:
                logging.error(f"  ✗ Failed to set focus: {e}")
        
        logging.info("\n" + "=" * 80)
        logging.info("Focus motor diagnostic complete\n" + "=" * 80)
        logging.info()
        
        # Cleanup
        hololink.stop()
        
        return True
        
    except Exception as e:
        logging.error(f"Test failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test IMX258 focus motor")
    parser.add_argument("--camera-ip", type=str, default="192.168.0.2", help="Hololink device IP")
    parser.add_argument("--camera-id", type=int, default=0, choices=[0, 1], help="Camera index")
    args = parser.parse_args()
    
    test_focus_motor(args.camera_ip, args.camera_id)
