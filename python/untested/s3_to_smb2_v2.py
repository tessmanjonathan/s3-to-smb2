import boto3
import smbprotocol
from smbprotocol.connection import Connection, Dialects
from smbprotocol.session import Session
from smbprotocol.open import Open, FileAttributes, ShareAccess, CreateDisposition
import argparse
import logging
import time
import uuid
from getpass import getpass

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_args():
    parser = argparse.ArgumentParser(description="Transfer file from S3 to SMB2 share")
    parser.add_argument('--bucket', required=True, help="S3 bucket name")
    parser.add_argument('--key', required=True, help="S3 object key")
    parser.add_argument('--smb-path', required=True, help="SMB UNC path (e.g., \\server\share\file.dat)")
    parser.add_argument('--username', required=True, help="AD username")
    parser.add_argument('--domain', default="", help="AD domain")
    parser.add_argument('--buffer-size', type=int, choices=[65536, 262144, 1048576], default=1048576,
                        help="Write buffer size in bytes (64KB, 256KB, 1MB)")
    return parser.parse_args()

def transfer_file(bucket, key, smb_path, username, password, domain, buffer_size):
    start_time = time.time()
    write_operations = 0

    # Initialize S3 client
    s3 = boto3.client('s3')

    # Initialize SMB2 connection
    smbprotocol.ClientConfig(require_secure_negotiate=False)  # Disable secure negotiation for SMB2
    server, share_path = smb_path.replace('\\', '/').split('/', 3)[1:3]
    file_path = '/' + smb_path.replace('\\', '/').split('/', 3)[3]
    connection = Connection(uuid.uuid4(), server, 445)
    connection.connect(dialect=Dialects.SMB_2_0_2)  # Enforce SMB 2.0.2
    session = Session(connection, username, password, domain)
    session.connect()

    # Open SMB file
    tree = session.tree_connect(f"\\\\{server}\\{share_path}")
    max_write_size = connection.max_write_size
    write_size = min(buffer_size, max_write_size)
    logging.info(f"Using write size: {write_size} bytes (server max: {max_write_size})")

    file = Open(tree, file_path)
    file.create(file_attributes=FileAttributes.FILE_ATTRIBUTE_NORMAL,
                share_access=ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
                create_disposition=CreateDisposition.FILE_OVERWRITE_IF)

    # Stream from S3 to SMB
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        stream = response['Body']
        file_size = response['ContentLength']
        buffer = bytearray()

        for chunk in stream.iter_chunks(chunk_size=8192):
            buffer.extend(chunk)
            while len(buffer) >= write_size:
                file.write(buffer[:write_size])
                buffer = buffer[write_size:]
                write_operations += 1

        if buffer:
            file.write(buffer)
            write_operations += 1

        file.close()
        tree.disconnect()
        session.disconnect()
        connection.disconnect()

        # Calculate metrics
        end_time = time.time()
        duration = end_time - start_time
        throughput = file_size / duration if duration > 0 else 0
        logging.info(f"Transferred {file_size} bytes in {duration:.2f} seconds")
        logging.info(f"Throughput: {throughput:.2f} bytes/s")
        logging.info(f"Write operations: {write_operations}")
    except Exception as e:
        logging.error(f"Transfer failed: {e}")
        raise
    finally:
        file.close()
        tree.disconnect()
        session.disconnect()
        connection.disconnect()

def main():
    args = parse_args()
    password = getpass("Enter AD password: ")
    transfer_file(args.bucket, args.key, args.smb_path, args.username, password, args.domain, args.buffer_size)

if __name__ == "__main__":
    main()