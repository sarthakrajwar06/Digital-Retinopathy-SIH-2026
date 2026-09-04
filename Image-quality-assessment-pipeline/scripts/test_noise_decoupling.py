"""
Test deterministic noise decoupling algorithm on fundus images.
"""
import sys
sys.path.insert(0, '.')
import cv2
import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from src.fov_detector import detect_retinal_fov

# Load 50 sample images
df = pd.read_csv('reports/dataset_analysis.csv').head(50)

orig_noises = []
decoupled_noises = []
lap_vars = []

for idx, row in df.iterrows():
    fn = row['filename']
    img_path = f"dataset/{fn}"
    img = cv2.imread(img_path)
    if img is None:
        continue
    
    h, w, _ = img.shape
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    green = img[:, :, 1]
    
    fov_info = detect_retinal_fov(img)
    mask_eroded = fov_info['mask_eroded'] > 0
    
    # 1. Original noise residual
    blurred = cv2.GaussianBlur(gray, (5, 5), 1.0)
    residual = gray.astype(np.float32) - blurred.astype(np.float32)
    orig_noise = float(np.std(residual[mask_eroded]))
    orig_noises.append(orig_noise)
    
    # 2. Anatomical structure exclusion mask
    # Scale kernel size with image resolution
    scale = max(w, h) / 1024.0
    k_size = max(5, int(11 * scale)) | 1
    
    # Black-hat extracts dark tubular vessels in green channel
    k_struct = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_size, k_size))
    blackhat = cv2.morphologyEx(green, cv2.MORPH_BLACKHAT, k_struct)
    
    # High-gradient edges using Sobel magnitude
    sobel_x = cv2.Sobel(green, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(green, cv2.CV_32F, 0, 1, ksize=3)
    edge_mag = np.sqrt(sobel_x**2 + sobel_y**2)
    
    # Detect structures in eroded retinal field
    retina_edges = edge_mag[mask_eroded]
    retina_bhat = blackhat[mask_eroded]
    
    thresh_edge = np.percentile(retina_edges, 70)
    thresh_bhat = np.percentile(retina_bhat, 70)
    
    vessel_edge_mask = (edge_mag > thresh_edge) | (blackhat > thresh_bhat)
    
    # Dilate slightly to exclude blur transition zones
    k_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(5 * scale)) | 1, max(3, int(5 * scale)) | 1))
    dilated_vessels = cv2.dilate(vessel_edge_mask.astype(np.uint8), k_dilate) > 0
    
    # Homogeneous parenchyma mask
    parenchyma_mask = mask_eroded & (~dilated_vessels)
    
    # Safety guard: ensure at least 15% of retina remains
    if np.count_nonzero(parenchyma_mask) < 0.15 * np.count_nonzero(mask_eroded):
        parenchyma_mask = mask_eroded
        
    decoupled_noise = float(np.std(residual[parenchyma_mask]))
    decoupled_noises.append(decoupled_noise)
    lap_vars.append(row['focus_var_laplacian'])

r_orig, _ = pearsonr(orig_noises, lap_vars)
r_decoupled, _ = pearsonr(decoupled_noises, lap_vars)

print(f"Evaluated on {len(lap_vars)} images:")
print(f"Original Noise vs Laplacian correlation:  {r_orig:.4f}")
print(f"Decoupled Noise vs Laplacian correlation: {r_decoupled:.4f}")
print(f"Correlation reduction: {abs(r_orig) - abs(r_decoupled):.4f} (from {r_orig:.4f} down to {r_decoupled:.4f})")
