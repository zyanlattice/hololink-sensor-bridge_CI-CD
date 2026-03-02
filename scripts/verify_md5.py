import hashlib
import argparse
import os

   

def measure_file(filename) -> str:
        image, metadata, content = fetch_file(filename)
        md5 = hashlib.md5(content).hexdigest()
        
        return md5

def fetch_file(filename):
    p = os.path.split(filename)
    image = p[-1]
    with open(filename, "rb") as f:
        content = f.read()
    metadata = {
        "filename": filename,
    }
    return image, metadata, content

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bitstream-path", required=True, type=str, help="Bitstream file path (local file path)")
    parser.add_argument("--md5", type=str, help="Expected MD5 checksum (hex string)")

    return parser.parse_args()

def main():

    args = parse_args()

    generated_md5 = measure_file(args.bitstream_path)
    print(f"Generated MD5 checksum: {generated_md5}")

    if args.md5 is None:
        print("No expected MD5 provided for comparison")
        return True
    
    if args.md5 == generated_md5:
        print("✓ MD5 checksum matches expected value.")
        return True
    else:
        print(f"✗ Generated MD5 checksum {generated_md5} does NOT match expected value {args.md5}!")
        return False

if __name__ == "__main__":
    main()