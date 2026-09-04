import cv2, sys
sys.path.insert(0, '.')
import numpy as np
from src.fov_detector import detect_retinal_fov
from src.quality_metrics import compute_image_quality_metrics
from src.quality_classifier import classify_fundus_image_quality

img = cv2.imread('dataset/aptos_9c5dd3612f0c.png')
fov = detect_retinal_fov(img)
m_orig = compute_image_quality_metrics(img, fov)
m_orig['width'] = img.shape[1]
m_orig['height'] = img.shape[0]
c_orig = classify_fundus_image_quality(m_orig)
print(f"aptos_9c5dd3612f0c Original: focus={c_orig['score_focus']:.3f}, noise={c_orig['score_noise']:.3f}, lap={m_orig['focus_var_laplacian']:.1f}")

# Gentle bilateral filter
denoised = cv2.bilateralFilter(img, d=3, sigmaColor=15.0, sigmaSpace=5.0)
m_post = compute_image_quality_metrics(denoised, fov)
m_post['width'] = img.shape[1]
m_post['height'] = img.shape[0]
c_post = classify_fundus_image_quality(m_post)
print(f"Gentle Denoised: focus={c_post['score_focus']:.3f}, noise={c_post['score_noise']:.3f}, lap={m_post['focus_var_laplacian']:.1f}")
