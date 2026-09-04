"""
Test glare correction on aptos_15cc2aef772a.png.
"""
import sys
sys.path.insert(0, '.')
import cv2
import numpy as np
from src.fov_detector import detect_retinal_fov
from src.quality_metrics import compute_image_quality_metrics
from src.quality_classifier import classify_fundus_image_quality

def test_glare_on_aptos():
    fn = 'dataset/aptos_15cc2aef772a.png'
    img = cv2.imread(fn)
    fov_info = detect_retinal_fov(img)
    mask = fov_info['mask_eroded'] > 0
    h, w = img.shape[:2]

    m_orig = compute_image_quality_metrics(img, fov_info)
    m_orig['width'] = w
    m_orig['height'] = h
    c_orig = classify_fundus_image_quality(m_orig)
    print(f"aptos_15cc2aef772a Original: status={c_orig['status']}, overall={c_orig['overall_score']:.4f}, score_art={c_orig['score_artifact']:.4f}, blobs={m_orig['artifact_glare_blob_count']}, sat_pct={m_orig['artifact_sat_pixel_pct']:.4f}%")

    # Detect glare blobs inside mask
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sat_mask = (gray > 240) & mask
    
    # Filter small punctate blobs (< 250 px)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(sat_mask.astype(np.uint8))
    inpaint_mask = np.zeros_like(sat_mask, dtype=np.uint8)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area <= 250:
            inpaint_mask[labels == i] = 255
            
    # Dilate by 2 px
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    inpaint_mask = cv2.dilate(inpaint_mask, k)
    
    # Inpaint
    enhanced = cv2.inpaint(img, inpaint_mask, 3, cv2.INPAINT_TELEA)
    enhanced[~mask] = img[~mask]

    # Reassessment
    fov_post = detect_retinal_fov(enhanced)
    m_post = compute_image_quality_metrics(enhanced, fov_post)
    m_post['width'] = w
    m_post['height'] = h
    c_post = classify_fundus_image_quality(m_post)
    print(f"aptos_15cc2aef772a Post-Enh: status={c_post['status']}, overall={c_post['overall_score']:.4f}, score_art={c_post['score_artifact']:.4f}, blobs={m_post['artifact_glare_blob_count']}, sat_pct={m_post['artifact_sat_pixel_pct']:.4f}%")
    print(f"Score Delta: {c_post['overall_score'] - c_orig['overall_score']:+.4f}, Status: {c_orig['status']} -> {c_post['status']}")

if __name__ == '__main__':
    test_glare_on_aptos()
