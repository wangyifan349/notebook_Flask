import os
import threading
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.mac import Poly1305
from cryptography.hazmat.backends import default_backend

def generate_key():
    """Generate a ChaCha20 key."""
    return os.urandom(32)

def encrypt_file(file_path, key):
    """Encrypt the file and generate a MAC."""
    nonce = os.urandom(12)  # ChaCha20 uses a 12-byte nonce
    cipher = Cipher(algorithms.ChaCha20(key, nonce), mode=None, backend=default_backend())
    encryptor = cipher.encryptor()

    with open(file_path, 'rb') as file:
        plaintext = file.read()

    ciphertext = encryptor.update(plaintext)

    # Generate MAC
    poly1305 = Poly1305(key[32:])  # Use the last 16 bytes of the key as the Poly1305 key
    poly1305.update(nonce + ciphertext)
    mac = poly1305.finalize()

    # Overwrite the original file with nonce, ciphertext, and MAC
    with open(file_path, 'wb') as file:
        file.write(nonce + ciphertext + mac)

    print(f"File {file_path} encrypted successfully.")

def decrypt_file(file_path, key, failed_decryptions):
    """Decrypt the file and verify the MAC."""
    with open(file_path, 'rb') as file:
        nonce = file.read(12)  # Read nonce
        ciphertext = file.read(-16)  # Read ciphertext
        mac = file.read(16)  # Read MAC

    # Verify MAC
    poly1305 = Poly1305(key[32:])  # Use the last 16 bytes of the key as the Poly1305 key
    poly1305.update(nonce + ciphertext)
    try:
        poly1305.verify(mac)
    except Exception:
        print(f"MAC verification failed for file {file_path}. The file may have been tampered with.")
        failed_decryptions.append(file_path)
        return

    cipher = Cipher(algorithms.ChaCha20(key, nonce), mode=None, backend=default_backend())
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext)

    # Overwrite the original encrypted file with the decrypted content
    with open(file_path, 'wb') as file:
        file.write(plaintext)

    print(f"File {file_path} decrypted successfully.")

def process_file(file_path, key, mode, failed_decryptions):
    """Process a single file."""
    if mode == 'encrypt':
        encrypt_file(file_path, key)
    elif mode == 'decrypt':
        if file_path.endswith('.enc'):
            decrypt_file(file_path, key, failed_decryptions)

def process_directory(directory, key, mode):
    """Process all files in the specified directory."""
    threads = []
    failed_decryptions = []

    for root_directory, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root_directory, file)
            thread = threading.Thread(target=process_file, args=(file_path, key, mode, failed_decryptions))
            threads.append(thread)
            thread.start()

    for thread in threads:
        thread.join()

    return failed_decryptions

if __name__ == "__main__":
    mode = input("Please select mode (encrypt/decrypt): ").strip().lower()
    directory = input("Please enter the directory path to process: ").strip()
    key_file = "key.bin"

    # Read or generate the key
    if os.path.exists(key_file):
        with open(key_file, 'rb') as file:
            key = file.read()
    else:
        key = generate_key()
        with open(key_file, 'wb') as file:
            file.write(key)
        print(f"Generated and saved key to {key_file}")

    failed_decryptions = process_directory(directory, key, mode)

    if mode == 'decrypt':
        if failed_decryptions:
            print("Files that could not be successfully decrypted:")
            for file in failed_decryptions:
                print(file)
        else:
            print("All files decrypted successfully.")
