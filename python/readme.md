# SMB2 S3-to-FileShare Transfer Tool

A Python proof-of-concept application that demonstrates efficient SMB2 file transfers with configurable write buffer sizes. This tool downloads files directly from AWS S3 and writes them to SMB2 file shares, optimizing performance through larger write operations.

## Purpose

This application was created to demonstrate that SMB2 applications can be optimized for better performance by using larger write buffer sizes and avoiding unnecessary protocol renegotiations. It serves as a benchmark to compare against vendor applications that may be using inefficient small write sizes (e.g., 16KB with renegotiation for every write).

## Original Requirements

The application was built to meet these specific requirements:

1. **Protocol**: SMB2 specifically (not SMB3 or SMB1)
2. **Source**: Download directly from AWS S3 (using existing AWS profile/credentials)
3. **Destination**: SMB2 file share via UNC path (`\\server\share\file.dat`)
4. **Write buffer size**: CLI parameter with options like 64KB, 256KB, 1MB
5. **Authentication**: Username/password for AD domain (secure prompts)
6. **Goal**: Write files efficiently without unnecessary SMB2 renegotiation or small default chunks 16kb
7. **Metrics**: Basic performance info (time, throughput, write operation count)
8. **Complexity**: Simple POC with minimal error handling

## Installation

1. **Clone or download** the script files
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure AWS credentials** (if not already done):
   ```bash
   aws configure
   # or ensure AWS_PROFILE environment variable is set
   ```

## Usage

### Basic Usage
```bash
python s3_to_smb2.py \
    --server fileserver01.domain.com \
    --share data \
    --bucket my-s3-bucket \
    --s3-key test-files/1gb-testfile.dat \
    --smb-filename transferred-file.dat \
    --write-size 256KB
```

### Authentication
When you run the script, it will prompt for credentials:
```
SMB Authentication Required
Username (domain\username or username): MYDOMAIN\myuser
Password: [hidden input]
```

**Username Format Options:**
- `MYDOMAIN\myuser` - automatically parses domain and username
- `myuser` - uses empty domain (for workgroup scenarios)

### Command Line Arguments

| Argument | Required | Description | Example |
|----------|----------|-------------|---------|
| `--server` | Yes | SMB server hostname/IP | `fileserver01.domain.com` |
| `--share` | Yes | SMB share name | `data` |
| `--bucket` | Yes | S3 bucket name | `my-s3-bucket` |
| `--s3-key` | Yes | S3 object key | `test-files/1gb-file.dat` |
| `--smb-filename` | Yes | SMB destination filename | `transferred-file.dat` |
| `--write-size` | No | Write buffer size (default: 64KB) | `16KB`, `64KB`, `256KB`, `1MB` |

## Performance Testing Strategy

To demonstrate the performance benefits of larger write buffers, run the same file transfer with different write sizes:

```bash
# Test with small writes (like problematic vendor app)
python smb2_transfer.py ... --write-size 16KB

# Test with optimized writes
python smb2_transfer.py ... --write-size 64KB
python smb2_transfer.py ... --write-size 256KB
python smb2_transfer.py ... --write-size 1MB
```

## Expected Output

```
SMB Authentication Required
Username (domain\username or username): DOMAIN\testuser
Password: 
Write buffer size: 262,144 bytes (256KB)
Connecting to SMB2 server: fileserver01.domain.com
SMB2 Protocol negotiated: 0x0210
SMB2 session established
Connected to share: data
SMB2 Max Write Size: 1,048,576 bytes (1024KB)
S3 object size: 1,073,741,824 bytes (1024.0 MB)
Opened SMB2 file: transferred-file.dat
Starting transfer with 256KB write buffers...
Progress: 100.0% (1,073,741,824/1,073,741,824 bytes) - Operations: 4,096

=== Transfer Complete ===
Total time: 45.23 seconds
Bytes written: 1,073,741,824
Write operations: 4,096
Average write size: 262.1 KB
Throughput: 22.65 MB/s
Operations per second: 90.5

=== SUCCESS ===
File successfully transferred from S3 to SMB2 share
SMB2 connections closed
```

## How It Demonstrates Optimization

**The Problem**: Many applications use small write buffers (16KB) and renegotiate SMB2 for every write operation, leading to:
- Small write buffers are not an issue within a local data center and low latency.
- When moving applications to the Cloud some latency is added due to additional hops while a file server is remaining onprem or in another cloud environment
- High number of network round trips
- Protocol overhead for each small write
- Poor overall throughput

**The Solution**: This application demonstrates:
- Single SMB2 session establishment
- Large write buffers (up to SMB2 max write size)
- Fewer total write operations
- Better throughput and performance

**Example Comparison**:
- **16KB writes**: 1GB file = 65,536 write operations
- **256KB writes**: 1GB file = 4,096 write operations (16x fewer!)
- **1MB writes**: 1GB file = 1,024 write operations (64x fewer!)

## Requirements

- Python 3.7+
- AWS credentials configured (via `aws configure` or environment variables)
- Network access to both S3 and the target SMB2 server
- SMB2 server with appropriate share permissions
- Active Directory credentials (if using domain authentication)

## Troubleshooting

**SMB Connection Issues**:
- Verify server hostname/IP and share name
- Check network connectivity to SMB server
- Ensure credentials have access to the share
- Verify SMB2 is enabled on the server

**S3 Access Issues**:
- Confirm AWS credentials are properly configured
- Verify bucket name and object key exist
- Check S3 permissions for the object

**Performance Issues**:
- Try different write buffer sizes
- Check SMB2 server configuration (max write size settings)
- Monitor network bandwidth utilization
- Consider SMB2 server performance characteristics

## License

This is a proof-of-concept tool for demonstration purposes. Use at your own risk in production environments. Reach out or create an issue if you have any questions. This will not be maintained unless something is needed for the demonstration. More languages as examples besides python may be introduced.