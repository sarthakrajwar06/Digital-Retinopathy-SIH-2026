import os
import sys
import zipfile
import time

def extract_dataset(zip_path, target_dir):
    print(f"Starting extraction of {zip_path} to {target_dir}...")
    start_time = time.time()
    
    os.makedirs(target_dir, exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        members = zf.infolist()
        total_members = len(members)
        print(f"Total entries in zip archive: {total_members}")
        
        extracted_count = 0
        for i, member in enumerate(members, 1):
            zf.extract(member, target_dir)
            extracted_count += 1
            if i % 500 == 0 or i == total_members:
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                print(f"Extracted {i}/{total_members} files ({i/total_members*100:.1f}%) - {rate:.1f} files/sec")
                
    total_time = time.time() - start_time
    print(f"Extraction completed in {total_time:.2f} seconds ({extracted_count} entries extracted).")

if __name__ == '__main__':
    zip_file = r"C:\Users\SAMSUNG\OneDrive\Desktop\SIH\images.zip"
    dest_dir = r"D:\SIH_data\dataset"
    extract_dataset(zip_file, dest_dir)
