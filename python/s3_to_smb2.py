#!/usr/bin/env python3
import argparse
import time
import sys
import getpass
import uuid
import boto3
from smbprotocol.connection import Connection
from smbprotocol.session import Session
from smbprotocol.tree import TreeConnect
from smbprotocol.open import Open, CreateDisposition, CreateOptions, FileAttributes, ImpersonationLevel, ShareAccess
# from smbprotocol.file_info import FileStandardInformation
# from smbprotocol.exceptions import SMBException


class SMB2S3Transfer:
    def __init__(self, server, share, username, password, domain=""):
        self.server = server
        self.share = share
        self.username = username
        self.password = password
        self.domain = domain
        self.connection = None
        self.session = None
        self.tree = None
        self.s3_client = boto3.client('s3')
        
    def connect_smb2(self):
        """Establish SMB2 connection, session, and tree connect"""
        try:
            print(f"Connecting to SMB2 server: {self.server}")
            
            # Force SMB2 protocol (not SMB3)
            self.connection = Connection(uuid.uuid4(), self.server, 445)
            self.connection.connect()
            negotiate_response = self.connection.negotiate()
            if negotiate_response['dialect_revision'] not in [0x0202, 0x0210, 0x0300]:  # SMB 2.0.2, 2.1, 3.0
                print(f"Warning: Negotiated dialect: {hex(negotiate_response['dialect_revision'])}")
            
            print(f"SMB2 Protocol negotiated: {hex(negotiate_response['dialect_revision'])}")
            
            # Create session
            self.session = Session(self.connection, self.username, self.password, domain=self.domain)
            self.session.connect()
            print("SMB2 session established")
            
            # Connect to tree (share)
            self.tree = TreeConnect(self.session, f"\\\\{self.server}\\{self.share}")
            self.tree.connect()
            print(f"Connected to share: {self.share}")
            
            # Get max write size from negotiation
            max_write_size = self.connection.max_write_size
            print(f"SMB2 Max Write Size: {max_write_size:,} bytes ({max_write_size//1024}KB)")
            
            return max_write_size
            
        except Exception as e:
            print(f"SMB2 connection error: {e}")
            self.cleanup()
            raise
    
    def download_and_write(self, bucket, s3_key, smb_filename, write_buffer_size):
        """Download from S3 and write to SMB2 share with specified buffer size"""
        
        # Get S3 object info
        try:
            response = self.s3_client.head_object(Bucket=bucket, Key=s3_key)
            file_size = response['ContentLength']
            print(f"S3 object size: {file_size:,} bytes ({file_size//1024//1024:.1f} MB)")
        except Exception as e:
            print(f"S3 error getting object info: {e}")
            raise
        
        # Open SMB2 file for writing
        try:
            smb_file = Open(self.tree, smb_filename)
            smb_file.create(
                ImpersonationLevel.Impersonation,
                FileAttributes.FILE_ATTRIBUTE_NORMAL,
                ShareAccess.FILE_SHARE_READ,
                CreateDisposition.FILE_OVERWRITE_IF,
                CreateOptions.FILE_NON_DIRECTORY_FILE
            )
            print(f"Opened SMB2 file: {smb_filename}")
        except Exception as e:
            print(f"SMB2 file creation error: {e}")
            raise
        
        # Performance tracking
        start_time = time.time()
        bytes_written = 0
        write_operations = 0
        
        try:
            print(f"Starting transfer with {write_buffer_size//1024}KB write buffers...")
            
            bytes_downloaded = 0
            while bytes_downloaded < file_size:
                # Calculate range for this chunk
                end_byte = min(bytes_downloaded + write_buffer_size - 1, file_size - 1)
                range_header = f"bytes={bytes_downloaded}-{end_byte}"
                
                # Download chunk from S3
                chunk_response = self.s3_client.get_object(
                    Bucket=bucket, 
                    Key=s3_key,
                    Range=range_header
                )
                
                chunk_data = chunk_response['Body'].read()
                actual_chunk_size = len(chunk_data)
                
                if actual_chunk_size == 0:
                    break
                
                # Write chunk to SMB2
                smb_file.write(chunk_data, bytes_written)
                
                bytes_written += actual_chunk_size
                bytes_downloaded += actual_chunk_size
                write_operations += 1
                
                # Progress update
                progress = (bytes_written / file_size) * 100
                print(f"\rProgress: {progress:.1f}% ({bytes_written:,}/{file_size:,} bytes) "
                      f"- Operations: {write_operations}", end="", flush=True)
            
            print()  # New line after progress
            
        except Exception as e:
            print(f"\nTransfer error: {e}")
            raise
        finally:
            try:
                smb_file.close()
                print("SMB2 file closed")
            except:
                pass
        
        # Calculate performance metrics
        end_time = time.time()
        total_time = end_time - start_time
        throughput_mbps = (bytes_written / (1024 * 1024)) / total_time
        avg_write_size = bytes_written / write_operations if write_operations > 0 else 0
        
        print(f"\n=== Transfer Complete ===")
        print(f"Total time: {total_time:.2f} seconds")
        print(f"Bytes written: {bytes_written:,}")
        print(f"Write operations: {write_operations:,}")
        print(f"Average write size: {avg_write_size/1024:.1f} KB")
        print(f"Throughput: {throughput_mbps:.2f} MB/s")
        print(f"Operations per second: {write_operations/total_time:.1f}")
        
        return {
            'total_time': total_time,
            'bytes_written': bytes_written,
            'write_operations': write_operations,
            'throughput_mbps': throughput_mbps,
            'avg_write_size': avg_write_size
        }
    
    def cleanup(self):
        """Clean up SMB2 connections"""
        try:
            if self.tree:
                self.tree.disconnect()
            if self.session:
                self.session.logoff()
            if self.connection:
                self.connection.disconnect()
            print("SMB2 connections closed")
        except:
            pass


def parse_buffer_size(size_str):
    """Parse buffer size string (e.g., '64KB', '1MB') to bytes"""
    size_str = size_str.upper().strip()
    
    if size_str.endswith('KB'):
        return int(size_str[:-2]) * 1024
    elif size_str.endswith('MB'):
        return int(size_str[:-2]) * 1024 * 1024
    elif size_str.endswith('GB'):
        return int(size_str[:-2]) * 1024 * 1024 * 1024
    else:
        # assumed this is in 'bytes' at this point
        return int(size_str)


def get_credentials():
    """Prompt for SMB credentials securely"""
    print("SMB Authentication Required")
    username_input = input("Username (domain\\username or username): ").strip()
    
    if '\\' in username_input:
        domain, username = username_input.split('\\', 1)
    else:
        domain = ""
        username = username_input
    
    password = getpass.getpass("Password: ")
    
    return username, password, domain


def main():
    parser = argparse.ArgumentParser(description="SMB2 S3-to-FileShare Transfer Tool")
    
    parser.add_argument('--server', required=True, help='SMB server hostname/IP')
    parser.add_argument('--share', required=True, help='SMB share name')
    
    parser.add_argument('--bucket', required=True, help='S3 bucket name')
    parser.add_argument('--s3-key', required=True, help='S3 object key')
    parser.add_argument('--smb-filename', required=True, help='SMB destination filename')
    
    parser.add_argument('--write-size', default='64KB', 
                       help='Write buffer size (e.g., 16KB, 64KB, 256KB, 1MB)')
    
    args = parser.parse_args()
    
    username, password, domain = get_credentials()
    
    try:
        write_buffer_size = parse_buffer_size(args.write_size)
        print(f"Write buffer size: {write_buffer_size:,} bytes ({write_buffer_size//1024}KB)")
    except ValueError as e:
        print(f"Invalid write size format: {args.write_size}")
        sys.exit(1)
    
    transfer = SMB2S3Transfer(
        args.server, args.share, username, password, domain
    )
    
    try:
        max_write_size = transfer.connect_smb2()
        
        # Check if requested write size exceeds negotiated maximum
        if write_buffer_size > max_write_size:
            print(f"Warning: Requested write size ({write_buffer_size//1024}KB) exceeds "
                  f"SMB2 max write size ({max_write_size//1024}KB)")
            print(f"Using SMB2 maximum: {max_write_size//1024}KB")
            write_buffer_size = max_write_size
        
        transfer.download_and_write(
            args.bucket, args.s3_key, args.smb_filename, write_buffer_size
        )
        
        print(f"\n=== SUCCESS ===")
        print(f"File successfully transferred from S3 to SMB2 share")
        
    except Exception as e:
        print(f"Transfer failed: {e}")
        sys.exit(1)
    finally:
        transfer.cleanup()


if __name__ == "__main__":
    main()