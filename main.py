import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from web_server import start_web_server

def main():
    print("Starting Padre Roble Exposition System...")
    start_web_server()

if __name__ == "__main__":
    main()
