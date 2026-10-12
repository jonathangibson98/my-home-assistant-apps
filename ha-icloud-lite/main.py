import os
import time

def main():
    username = os.getenv("ICLOUD_USERNAME")
    password = os.getenv("ICLOUD_PASSWORD")
    
    print(f"Starting service for iCloud user: {username}")
    
    # Add your iCloud tracking logic here later!
    while True:
        print("Checking iCloud locations...")
        time.sleep(60)

if __name__ == "__main__":
    main()
