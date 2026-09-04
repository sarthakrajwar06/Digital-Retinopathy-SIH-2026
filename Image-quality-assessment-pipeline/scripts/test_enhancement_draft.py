"""
Test enhancement operations on key borderline images.
"""
import sys
sys.path.insert(0, '.')
import cv2
import numpy as np
from src.fov_detector import detect_retinal_fov
from src.quality_metrics import compute_image_quality_metrics
from src.quality_classifier import classify_fundus_image_quality

def test_illumination_on_idrid():
    fn = 'dataset/train_IDRiD_352.jpg'
    img = cv2.imread(fn)
    fov_info = detect_retinal_fov(img)
    mask = fov_info['mask_eroded'] > 0
    h, w = img.shape[:2]

    # Original metrics
    m_orig = compute_image_quality_metrics(img, fov_info)
    m_orig['width'] = w
    m_orig['height'] = h
    c_orig = classify_fundus_image_quality(m_orig)
    print(f"train_IDRiD_352 Original: status={c_orig['status']}, overall={c_orig['overall_score']:.4f}, score_illum={c_orig['score_illumination']:.4f}, ratio={m_orig['illum_center_edge_ratio']:.3f}, cov={m_orig['illum_map_cov']:.3f}")

    # Illumination correction on L channel of LAB
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0].astype(np.float32)

    sigma = max(w, h) * 0.05
    mask_f = mask.astype(np.float32)
    L_masked = L * mask_f
    L_blur = cv2.GaussianBlur(L_masked, (0, 0), sigma)
    M_blur = cv2.GaussianBlur(mask_f, (0, 0), sigma)
    B = np.zeros_like(L)
    valid = M_blur > 1e-4
    B[valid] = L_blur[valid] / M_blur[valid]

    L_mean = float(np.mean(L[mask]))
    gain = np.ones_like(L)
    gain[mask] = L_mean / np.maximum(10.0, B[mask])
    gain = np.clip(gain, 0.75, 1.35)

    L_corr = np.clip(L * gain, 0, 255).astype(np.uint8)
    lab[:, :, 0] = np.where(mask, L_corr, lab[:, :, 0])
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    enhanced[~mask] = img[~mask]

    # Reassessment
    fov_post = detect_retinal_fov(enhanced)
    m_post = compute_image_quality_metrics(enhanced, fov_post)
    m_post['width'] = w
    m_post['height'] = h
    c_post = classify_fundus_image_quality(m_post)
    print(f"train_IDRiD_352 Post-Enh: status={c_post['status']}, overall={c_post['overall_score']:.4f}, score_illum={c_post['score_illumination']:.4f}, ratio={m_post['illum_center_edge_ratio']:.3f}, cov={m_post['illum_map_cov']:.3f}")
    print(f"Score Delta: {c_post['overall_score'] - c_orig['overall_score']:+.4f}, Status: {c_orig['status']} -> {c_post['status']}")

def test_clahe_on_contrast():
    fn = 'dataset/aptos_1e036f2e7095.png'
    img = cv2.imread(fn)
    fov_info = detect_retinal_fov(img)
    mask = fov_info['mask_eroded'] > 0
    h, w = img.shape[:2]

    m_orig = compute_image_quality_metrics(img, fov_info)
    m_orig['width'] = w
    m_orig['height'] = h
    c_orig = classify_fundus_image_quality(m_orig)
    print(f"\naptos_1e036f2e7095 Original: status={c_orig['status']}, overall={c_orig['overall_score']:.4f}, score_contrast={c_orig['score_contrast']:.4f}, rms={m_orig['contrast_rms']:.2f}")

    # Apply CLAHE on L channel of LAB
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    L = lab[:, :, 0]
    L_clahe = clahe.apply(L)
    lab[:, :, 0] = np.where(mask, L_clahe, L)
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    enhanced[~mask] = img[~mask]

    # Reassessment
    fov_post = detect_retinal_fov(enhanced)
    m_post = compute_image_quality_metrics(enhanced, fov_post)
    m_post['width'] = w
    m_post['height'] = h
    c_post = classify_fundus_image_quality(m_post)
    print(f"aptos_1e036f2e7095 Post-Enh: status={c_post['status']}, overall={c_post['overall_score']:.4f}, score_contrast={c_post['score_contrast']:.4f}, rms={m_post['contrast_rms']:.2f}")
    print(f"Score Delta: {c_post['overall_score'] - c_orig['overall_score']:+.4f}, Status: {c_orig['status']} -> {c_post['status']}")

if __name__ == '__main__':
    test_illumination_on_idrid()
    test_clahe_on_contrast()
