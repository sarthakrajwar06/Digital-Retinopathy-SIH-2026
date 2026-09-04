"""
Module 1: Fundus Image Quality Assessment
Phase 1-5 Performance Benchmark & Diagnostic Profiler on 50 Representative Images.

Measures:
- Per-image execution time
- Progress after EVERY image
- Progress summary every 10 images
- Granular sub-step timing for:
    * File reading & decoding
    * File inventory & hashing
    * FOV detection
    * Focus / blur metrics
    * Brightness / exposure metrics
    * Contrast metrics
    * Noise metrics
    * Illumination metrics
    * Artifacts metrics
- Debug visualizations for only 5 representative images
- Identification of the slowest function
- Total benchmark execution time and projection for all 4,178 images
"""

import os
import sys
import time
from collections import defaultdict
import numpy as np
import pandas as pd
import cv2
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dataset_inspector import inspect_single_file
from src.fov_detector import detect_retinal_fov
from src.quality_metrics import compute_image_quality_metrics


def select_50_representative_images(dataset_dir):
    """
    Select 50 representative images balancing both APTOS (PNG) and IDRiD (JPG) sources,
    covering varied resolutions and file sizes.
    """
    all_files = sorted([
        f for f in os.listdir(dataset_dir)
        if not f.endswith('.xlsx') and not f.endswith('.csv') and os.path.isfile(os.path.join(dataset_dir, f))
    ])
    
    png_files = [f for f in all_files if f.lower().endswith('.png')]
    jpg_files = [f for f in all_files if f.lower().endswith('.jpg')]
    
    # Take 25 evenly spaced PNGs and 25 evenly spaced JPGs
    step_png = max(1, len(png_files) // 25)
    sample_png = png_files[::step_png][:25]
    
    step_jpg = max(1, len(jpg_files) // 25)
    sample_jpg = jpg_files[::step_jpg][:25]
    
    sample = sample_png + sample_jpg
    # If less than 50, pad with remaining
    if len(sample) < 50:
        remaining = [f for f in all_files if f not in sample]
        sample.extend(remaining[:50 - len(sample)])
        
    return sample[:50]


def profile_single_image(filepath, fname):
    """
    Execute inspection, FOV detection, and quality metrics with granular sub-operation profiling.
    """
    timings = {}
    
    # 1. File inventory / hashing (Phase 1)
    t0 = time.perf_counter()
    p1_info = inspect_single_file(filepath)
    timings['phase1_inventory'] = time.perf_counter() - t0
    
    # 2. Image reading & decoding (OpenCV)
    t0 = time.perf_counter()
    img = cv2.imread(filepath)
    timings['image_decode'] = time.perf_counter() - t0
    
    if img is None:
        return None, timings, "Failed to decode"
        
    h, w, c = img.shape
    
    # 3. FOV Detection
    t0 = time.perf_counter()
    fov_info = detect_retinal_fov(img)
    timings['fov_detection'] = time.perf_counter() - t0
    
    # 4. Detailed profiling of Quality Metrics sub-steps
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = fov_info['mask']
    mask_eroded = fov_info['mask_eroded']
    retina_mask_bool = mask > 0
    eroded_mask_bool = mask_eroded > 0
    
    retina_gray = gray[retina_mask_bool]
    eroded_gray = gray[eroded_mask_bool]
    if len(retina_gray) == 0:
        retina_gray = gray.ravel()
        eroded_gray = gray.ravel()
        retina_mask_bool = np.ones((h, w), dtype=bool)
        eroded_mask_bool = np.ones((h, w), dtype=bool)
    elif len(eroded_gray) == 0:
        eroded_gray = retina_gray
        eroded_mask_bool = retina_mask_bool

    # 4A. Focus / Blur
    t0 = time.perf_counter()
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    lap_retina = lap[eroded_mask_bool]
    var_laplacian = float(np.var(lap_retina))
    laplacian_energy = float(np.mean(np.square(lap_retina)))
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    sobel_mag_sq = sobel_x**2 + sobel_y**2
    sobel_mag = np.sqrt(sobel_mag_sq)
    tenengrad = float(np.mean(sobel_mag_sq[eroded_mask_bool]))
    sobel_mean = float(np.mean(sobel_mag[eroded_mask_bool]))
    timings['metric_focus'] = time.perf_counter() - t0
    
    # 4B. Brightness / Exposure
    t0 = time.perf_counter()
    mean_intensity = float(np.mean(retina_gray))
    median_intensity = float(np.median(retina_gray))
    pcts = np.percentile(retina_gray, [5, 10, 25, 75, 90, 95])
    dark_pct = float(np.mean(retina_gray < 20) * 100.0)
    bright_pct = float(np.mean(retina_gray > 240) * 100.0)
    timings['metric_brightness'] = time.perf_counter() - t0
    
    # 4C. Contrast
    t0 = time.perf_counter()
    grayscale_std = float(np.std(retina_gray))
    rms_contrast = grayscale_std
    hist_spread = float(pcts[5] - pcts[0])
    hist_iqr = float(pcts[3] - pcts[2])
    michelson = float((pcts[5] - pcts[0]) / (pcts[5] + pcts[0] + 1e-5))
    timings['metric_contrast'] = time.perf_counter() - t0
    
    # 4D. Noise
    t0 = time.perf_counter()
    blurred = cv2.GaussianBlur(gray, (5, 5), 1.0)
    residual = gray.astype(np.float32) - blurred.astype(np.float32)
    res_retina = residual[eroded_mask_bool]
    noise_std = float(np.std(res_retina))
    noise_mad = float(np.mean(np.abs(res_retina - np.mean(res_retina))))
    gray_f = gray.astype(np.float32)
    local_mean = cv2.blur(gray_f, (7, 7))
    local_mean_sq = cv2.blur(gray_f ** 2, (7, 7))
    local_var = np.maximum(0.0, local_mean_sq - (local_mean ** 2))
    loc_var_retina = local_var[eroded_mask_bool]
    local_var_mean = float(np.mean(loc_var_retina))
    local_var_median = float(np.median(loc_var_retina))
    timings['metric_noise'] = time.perf_counter() - t0
    
    # 4E. Illumination
    t0 = time.perf_counter()
    scale_illum = 256.0 / max(h, w)
    small_green = cv2.resize(img[:, :, 1], (0, 0), fx=scale_illum, fy=scale_illum, interpolation=cv2.INTER_AREA)
    small_mask = cv2.resize(mask, (small_green.shape[1], small_green.shape[0]), interpolation=cv2.INTER_NEAREST)
    small_eroded = cv2.resize(mask_eroded, (small_green.shape[1], small_green.shape[0]), interpolation=cv2.INTER_NEAREST)
    illum_blur = cv2.GaussianBlur(small_green.astype(np.float32), (0, 0), sigmaX=15.0)
    illum_mask_bool = small_eroded > 0 if np.count_nonzero(small_eroded > 0) > 0 else small_mask > 0
    illum_vals = illum_blur[illum_mask_bool]
    illum_cov = float(np.std(illum_vals) / (np.mean(illum_vals) + 1e-5))
    
    # Center vs edge
    cx, cy = fov_info['centroid']
    y_coords, x_coords = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((x_coords - cx)**2 + (y_coords - cy)**2)
    r_est = fov_info['radius_est']
    center_zone = (dist_from_center <= 0.45 * r_est) & retina_mask_bool
    edge_zone = (dist_from_center >= 0.70 * r_est) & (dist_from_center <= 0.95 * r_est) & retina_mask_bool
    c_mean = float(np.mean(gray[center_zone])) if np.count_nonzero(center_zone) > 50 else mean_intensity
    e_mean = float(np.mean(gray[edge_zone])) if np.count_nonzero(edge_zone) > 50 else mean_intensity
    ce_ratio = float(c_mean / (e_mean + 1e-5))
    timings['metric_illumination'] = time.perf_counter() - t0
    
    # 4F. Artifacts
    t0 = time.perf_counter()
    sat_cond = (img[:, :, 0] >= 245) & (img[:, :, 1] >= 245) & (img[:, :, 2] >= 245) | (gray >= 250)
    sat_retina = sat_cond & eroded_mask_bool
    sat_pct = float(np.count_nonzero(sat_retina) / max(1, fov_info['retinal_area']) * 100.0)
    sat_uint8 = sat_retina.astype(np.uint8) * 255
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(sat_uint8, connectivity=8)
    glare_count = sum(1 for i in range(1, num_labels) if stats[i, cv2.CC_STAT_AREA] >= 20)
    timings['metric_artifacts'] = time.perf_counter() - t0
    
    timings['quality_metrics_total'] = (
        timings['metric_focus'] + timings['metric_brightness'] + timings['metric_contrast'] +
        timings['metric_noise'] + timings['metric_illumination'] + timings['metric_artifacts']
    )
    
    timings['total_image_time'] = (
        timings['phase1_inventory'] + timings['image_decode'] +
        timings['fov_detection'] + timings['quality_metrics_total']
    )
    
    record = {
        'filename': fname,
        'width': w,
        'height': h,
        'megapixels': round((w * h) / 1e6, 2),
        'file_format': p1_info['file_format'],
        'focus_var_laplacian': var_laplacian,
        'brightness_mean': mean_intensity,
        'contrast_rms': rms_contrast,
        'noise_residual_std': noise_std,
        'fov_coverage': fov_info['fov_coverage'],
        'illum_map_cov': illum_cov,
        'illum_center_edge_ratio': ce_ratio,
        'artifact_sat_pixel_pct': sat_pct,
        'artifact_glare_blob_count': glare_count
    }
    
    return record, timings, None


def generate_5_representative_visualizations(df, dataset_dir, debug_dir):
    """
    Generate debug visualizations for only 5 representative archetypes:
    1. Very sharp
    2. Very blurry
    3. Very dark
    4. Very bright
    5. Uneven illumination
    """
    os.makedirs(debug_dir, exist_ok=True)
    
    t_start = time.perf_counter()
    reps = {
        'sharp': df.sort_values(by='focus_var_laplacian', ascending=False).iloc[0],
        'blurry': df.sort_values(by='focus_var_laplacian', ascending=True).iloc[0],
        'dark': df.sort_values(by='brightness_mean', ascending=True).iloc[0],
        'bright': df.sort_values(by='brightness_mean', ascending=False).iloc[0],
        'uneven_illum': df.sort_values(by='illum_map_cov', ascending=False).iloc[0]
    }
    
    for cat, row in reps.items():
        fname = row['filename']
        img_bgr = cv2.imread(os.path.join(dataset_dir, fname))
        if img_bgr is None:
            continue
        h, w = img_bgr.shape[:2]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        fov_res = detect_retinal_fov(img_bgr)
        mask = fov_res['mask']
        cx, cy = fov_res['centroid']
        radius = fov_res['radius_est']
        
        fig, axes = plt.subplots(1, 4, figsize=(20, 5))
        fig.suptitle(f"Sample-50 Benchmark Debug — {cat.upper()} ({fname}, {w}x{h})", fontsize=13, fontweight='bold')
        
        axes[0].imshow(img_rgb)
        axes[0].set_title(f"1. Original\nMean={row['brightness_mean']:.1f}, LapVar={row['focus_var_laplacian']:.1f}")
        axes[0].axis('off')
        
        axes[1].imshow(mask, cmap='gray')
        axes[1].set_title(f"2. Retinal Mask\nCoverage: {row['fov_coverage']*100:.1f}%")
        axes[1].axis('off')
        
        bound_vis = img_rgb.copy()
        if fov_res['contour'] is not None:
            cv2.drawContours(bound_vis, [fov_res['contour']], -1, (0, 255, 0), max(2, int(min(h, w) * 0.003)))
        cv2.circle(bound_vis, (cx, cy), max(3, int(min(h, w) * 0.006)), (255, 0, 0), -1)
        axes[2].imshow(bound_vis)
        axes[2].set_title("3. Retinal Boundary & Centroid")
        axes[2].axis('off')
        
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        if cat in ('sharp', 'blurry'):
            lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
            lap[mask == 0] = 0
            vmax = np.percentile(lap[mask > 0], 99) if np.count_nonzero(mask) > 0 else 50
            axes[3].imshow(lap, cmap='inferno', vmin=0, vmax=vmax)
            axes[3].set_title(f"4. Laplacian Map (LapVar={row['focus_var_laplacian']:.1f})")
        else:
            scale_i = 256.0 / max(h, w)
            sg = cv2.resize(img_bgr[:, :, 1], (0, 0), fx=scale_i, fy=scale_i, interpolation=cv2.INTER_AREA)
            illum = cv2.GaussianBlur(sg.astype(np.float32), (0, 0), sigmaX=15.0)
            illum_full = cv2.resize(illum, (w, h), interpolation=cv2.INTER_LINEAR)
            illum_full[mask == 0] = 0
            axes[3].imshow(illum_full, cmap='magma')
            axes[3].set_title(f"4. Illumination Map (CoV={row['illum_map_cov']:.3f})")
        axes[3].axis('off')
        
        plt.tight_layout()
        base_name = os.path.splitext(fname)[0]
        out_p = os.path.join(debug_dir, f"sample50_{cat}_{base_name}.png")
        fig.savefig(out_p, dpi=150)
        plt.close(fig)
        
    total_vis_time = time.perf_counter() - t_start
    return total_vis_time


def run_benchmark():
    dataset_dir = r"C:\Users\SAMSUNG\OneDrive\Desktop\SIH\dataset"
    debug_dir = r"C:\Users\SAMSUNG\OneDrive\Desktop\SIH\data\debug"
    
    print("=" * 70)
    print("FAST DATASET ANALYSIS & BENCHMARK (50 REPRESENTATIVE IMAGES)")
    print("=" * 70)
    
    images_50 = select_50_representative_images(dataset_dir)
    print(f"Selected 50 representative images: {len([f for f in images_50 if f.endswith('.png')])} PNGs, {len([f for f in images_50 if f.endswith('.jpg')])} JPGs")
    print("-" * 70)
    
    timing_accumulator = defaultdict(list)
    records = []
    
    t_bench_start = time.perf_counter()
    
    for idx, fname in enumerate(images_50, 1):
        fpath = os.path.join(dataset_dir, fname)
        rec, timings, err = profile_single_image(fpath, fname)
        if err:
            print(f"[Image {idx:02d}/50] {fname} FAILED: {err}")
            continue
            
        records.append(rec)
        for k, v in timings.items():
            timing_accumulator[k].append(v)
            
        # Print progress after EVERY image
        print(f"[Image {idx:02d}/50] {fname:<24} ({rec['width']}x{rec['height']}, {rec['megapixels']}MP, {rec['file_format']}) | Total: {timings['total_image_time']*1000:6.1f}ms | Decode: {timings['image_decode']*1000:5.1f}ms | FOV: {timings['fov_detection']*1000:5.1f}ms | Metrics: {timings['quality_metrics_total']*1000:5.1f}ms | P1: {timings['phase1_inventory']*1000:5.1f}ms")
        
        # Print summary every 10 images
        if idx % 10 == 0:
            avg_so_far = np.mean(timing_accumulator['total_image_time']) * 1000
            print(f">>> MILESTONE {idx:02d}/50: Average Time = {avg_so_far:.1f} ms/image ({1000/avg_so_far:.2f} img/sec on single core) <<<")
            
    total_image_proc_time = time.perf_counter() - t_bench_start
    df = pd.DataFrame(records)
    
    # Generate 5 representative debug visualizations
    print("\nGenerating debug visualizations for 5 representative archetypes...")
    vis_time = generate_5_representative_visualizations(df, dataset_dir, debug_dir)
    print(f"Generated 5 debug visualizations in {vis_time:.2f} seconds.")
    
    total_wall_time = time.perf_counter() - t_bench_start
    
    # Calculate statistics across all 50 images
    sub_metrics = [
        ('File Inventory (PIL verify+hash)', 'phase1_inventory'),
        ('Image Reading & Decoding (cv2)', 'image_decode'),
        ('Retinal FOV Detection', 'fov_detection'),
        ('Focus / Blur Metrics', 'metric_focus'),
        ('Brightness Metrics', 'metric_brightness'),
        ('Contrast Metrics', 'metric_contrast'),
        ('Noise & Local Var Metrics', 'metric_noise'),
        ('Illumination Zone & Map Metrics', 'metric_illumination'),
        ('Artifact & Glare Metrics', 'metric_artifacts'),
    ]
    
    print("\n" + "=" * 70)
    print("DETAILED BREAKDOWN BY FUNCTION / SUB-OPERATION (AVERAGE PER IMAGE)")
    print("=" * 70)
    
    results_table = []
    for label, key in sub_metrics:
        vals = timing_accumulator[key]
        avg_ms = np.mean(vals) * 1000
        std_ms = np.std(vals) * 1000
        min_ms = np.min(vals) * 1000
        max_ms = np.max(vals) * 1000
        pct_total = (np.sum(vals) / np.sum(timing_accumulator['total_image_time'])) * 100
        results_table.append({
            'Operation': label,
            'Key': key,
            'Mean_ms': avg_ms,
            'Std_ms': std_ms,
            'Min_ms': min_ms,
            'Max_ms': max_ms,
            'Pct_Total': pct_total
        })
        print(f"  {label:<35}: {avg_ms:6.1f} ms ± {std_ms:5.1f} ms  (Min: {min_ms:5.1f}, Max: {max_ms:5.1f}) [{pct_total:5.1f}%]")
        
    # Sort to identify slowest function
    results_table.sort(key=lambda x: x['Mean_ms'], reverse=True)
    slowest_op = results_table[0]
    
    avg_total_ms = np.mean(timing_accumulator['total_image_time']) * 1000
    avg_fov_ms = np.mean(timing_accumulator['fov_detection']) * 1000
    avg_qm_ms = np.mean(timing_accumulator['quality_metrics_total']) * 1000
    
    # Projections for 4,178 images
    total_imgs = 4178
    single_core_hrs = (avg_total_ms / 1000.0 * total_imgs) / 3600.0
    eight_core_mins = ((avg_total_ms / 1000.0 * total_imgs) / 8.0) / 60.0
    ten_core_mins = ((avg_total_ms / 1000.0 * total_imgs) / 10.0) / 60.0
    
    print("\n" + "=" * 70)
    print("FINAL BENCHMARK SUMMARY (50 IMAGES)")
    print("=" * 70)
    print(f"Total Execution Time (50 images + vis) : {total_wall_time:.2f} seconds")
    print(f"Average Processing Time / Image       : {avg_total_ms:.1f} ms ({avg_total_ms/1000:.3f} s)")
    print(f"FOV Detection Time / Image            : {avg_fov_ms:.1f} ms ({avg_fov_ms/avg_total_ms*100:.1f}%)")
    print(f"Quality Metrics Time / Image          : {avg_qm_ms:.1f} ms ({avg_qm_ms/avg_total_ms*100:.1f}%)")
    print(f"Visualization Time (5 images)         : {vis_time:.2f} seconds ({vis_time/5:.2f} s/vis)")
    print(f"Slowest Function                      : {slowest_op['Operation']} ({slowest_op['Mean_ms']:.1f} ms, {slowest_op['Pct_Total']:.1f}% of total time)")
    print(f"Second Slowest Function               : {results_table[1]['Operation']} ({results_table[1]['Mean_ms']:.1f} ms, {results_table[1]['Pct_Total']:.1f}% of total time)")
    print(f"Third Slowest Function                : {results_table[2]['Operation']} ({results_table[2]['Mean_ms']:.1f} ms, {results_table[2]['Pct_Total']:.1f}% of total time)")
    print("-" * 70)
    print(f"Estimated Time for ALL 4,178 Images (Current Pipeline):")
    print(f"  - Single Core                       : {single_core_hrs:.2f} hours")
    print(f"  - 8 Worker Processes                : {eight_core_mins:.1f} minutes")
    print(f"  - 10 Worker Processes               : {ten_core_mins:.1f} minutes")
    print("=" * 70)


if __name__ == '__main__':
    run_benchmark()
