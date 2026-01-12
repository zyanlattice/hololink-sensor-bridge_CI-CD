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
    parser.add_argument(
        "--bitstream-path",
        required=True,
        type=str,
        help="Bitstream file path (local file path)",
    )

    return parser.parse_args()

def main():

    args = parse_args()

    md5 = measure_file(args.bitstream_path)
    print(f"MD5 checksum: {md5}")

    return md5

if __name__ == "__main__":
    main()