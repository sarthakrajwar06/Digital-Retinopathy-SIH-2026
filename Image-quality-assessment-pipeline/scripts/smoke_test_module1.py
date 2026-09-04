"""
Module 1: Image Quality Assessment & Triage Engine — Smoke Test Script
Location: scripts/smoke_test_module1.py

Purpose:
- Verify imports of all four Module 1 core files:
    1. src/config.py
    2. src/quality_metrics.py
    3. src/quality_classifier.py
    4. src/quality_enhancer.py
- Run the complete Module 1 pipeline on a single real fundus image from dataset/
- Print all 7 raw quality metrics and normalized dimension scores
- Print original status, enhancement operations, final status, and clinical flags
- Verify architectural invariants and dataset immutability
- Print "MODULE 1 SMOKE TEST: PASS" upon successful verification
"""

import os
import sys
import argparse

# Ensure project root is in Python sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main():
    print("=" * 80)
    print("MODULE 1: PRE-MEETING VERIFICATION SMOKE TEST")
    print("=" * 80)

    # -------------------------------------------------------------
    # 1. IMPORT ALL FOUR MODULE 1 PYTHON FILES
    # -------------------------------------------------------------
    print("\n[Step 1/5] Importing core Module 1 Python files...")
    try:
        import src.config as cfg
        print("  [OK] Successfully imported src.config")
    except Exception as e:
        print(f"  [FAIL] Failed to import src.config: {e}")
        sys.exit(1)

    try:
        from src.quality_metrics import compute_image_quality_metrics
        from src.fov_detector import detect_retinal_fov
        print("  [OK] Successfully imported src.quality_metrics (and src.fov_detector)")
    except Exception as e:
        print(f"  [FAIL] Failed to import src.quality_metrics: {e}")
        sys.exit(1)

    try:
        from src.quality_classifier import classify_fundus_image_quality
        print("  [OK] Successfully imported src.quality_classifier")
    except Exception as e:
        print(f"  [FAIL] Failed to import src.quality_classifier: {e}")
        sys.exit(1)

    try:
        from src.quality_enhancer import assess_and_enhance_pipeline
        print("  [OK] Successfully imported src.quality_enhancer")
    except Exception as e:
        print(f"  [FAIL] Failed to import src.quality_enhancer: {e}")
        sys.exit(1)

    import cv2
    import numpy as np

    # -------------------------------------------------------------
    # 2. LOCATE ONE REAL FUNDUS IMAGE FROM DATASET FOLDER
    # -------------------------------------------------------------
    print("\n[Step 2/5] Locating real fundus image from dataset/...")
    dataset_dir = os.path.join(PROJECT_ROOT, 'dataset')
    if not os.path.isdir(dataset_dir):
        print(f"  [FAIL] Dataset directory not found: {dataset_dir}")
        sys.exit(1)

    # Select representative image (supports positional arg, --image flag, or default fallback)
    parser = argparse.ArgumentParser(
        description="Module 1 Smoke Test",
        epilog="Examples:\n"
               "  py -3.13 scripts\\smoke_test_module1.py\n"
               "  py -3.13 scripts\\smoke_test_module1.py \"dataset\\aptos_000c1434d8d7.png\"\n"
               "  py -3.13 scripts\\smoke_test_module1.py \"C:\\Users\\SAMSUNG\\OneDrive\\Desktop\\SIH\\dataset\\aptos_000c1434d8d7.png\"\n"
               "  py -3.13 scripts\\smoke_test_module1.py aptos_000c1434d8d7.png\n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("image_path", nargs="?", default=None, help="Optional path to fundus image (relative, absolute, or filename in dataset/)")
    parser.add_argument("--image", type=str, default=None, help="Alternative flag for image path or filename")
    args, _ = parser.parse_known_args()

    target = args.image_path if args.image_path else args.image

    if target:
        target_clean = target.strip('\'"')
        potential_paths = [
            target_clean,                                        # Direct relative to CWD or absolute
            os.path.join(PROJECT_ROOT, target_clean),            # Relative to project root
            os.path.join(dataset_dir, target_clean),             # Relative to dataset dir
            os.path.join(dataset_dir, os.path.basename(target_clean))  # Basename inside dataset dir
        ]
        candidate_path = None
        for p in potential_paths:
            if os.path.isfile(p):
                candidate_path = os.path.abspath(p)
                break

        if candidate_path is None:
            print(f"  [FAIL] Could not locate image file from input: '{target}'")
            print("  Searched paths:")
            for p in potential_paths:
                print(f"    - {p}")
            sys.exit(1)
        candidate_name = os.path.basename(candidate_path)
    else:
        # Pick the first valid fundus image found in dataset/
        valid_extensions = ('.png', '.jpg', '.jpeg')
        candidates = sorted([f for f in os.listdir(dataset_dir) if f.lower().endswith(valid_extensions)])
        if not candidates:
            print(f"  [FAIL] No fundus images found in {dataset_dir}")
            sys.exit(1)
        candidate_name = candidates[0]
        candidate_path = os.path.abspath(os.path.join(dataset_dir, candidate_name))

    # Record pre-run file stats to verify dataset immutability
    initial_stat = os.stat(candidate_path)
    initial_size = initial_stat.st_size
    initial_mtime = initial_stat.st_mtime
    print(f"  Exact Image Path : {candidate_path}")
    print(f"  Filename         : {candidate_name}")
    print(f"  File Size        : {initial_size:,} bytes")

    # -------------------------------------------------------------
    # 3. RUN COMPLETE MODULE 1 PIPELINE ON SINGLE IMAGE
    # -------------------------------------------------------------
    print("\n[Step 3/5] Executing complete Module 1 pipeline...")
    
    # 3a. Basic Validation
    image_bgr = cv2.imread(candidate_path)
    if image_bgr is None:
        print(f"  [FAIL] cv2.imread failed to load image: {candidate_path}")
        sys.exit(1)
    h, w, c = image_bgr.shape
    print(f"  Image Loaded   : {w}x{h} (channels: {c})")
    assert h >= 100 and w >= 100, f"Image dimensions too small: {w}x{h}"

    # 3b. Direct extraction of raw quality metrics for transparent printing
    fov_info = detect_retinal_fov(image_bgr)
    raw_metrics = compute_image_quality_metrics(image_bgr, fov_info)
    raw_metrics['filename'] = candidate_name
    raw_metrics['width'] = w
    raw_metrics['height'] = h

    # 3c. Complete Module 1 pipeline execution using existing primary entry point
    pipeline_res, orig_bgr, enh_bgr = assess_and_enhance_pipeline(image_bgr, filename=candidate_name)

    # -------------------------------------------------------------
    # 4. PRINT REPORTED METRICS, SCORES, AND DIRECTIVES
    # -------------------------------------------------------------
    print("\n[Step 4/5] Detailed Quality Assessment & Decision Results:")
    print("-" * 80)
    print(f"  Image Filename             : {candidate_name}")
    print(f"  Exact Image Path           : {candidate_path}")
    print("-" * 80)

    print("  RAW QUALITY METRICS (7 Dimensions):")
    print(f"    1. Focus / Sharpness     : Laplacian Var = {raw_metrics['focus_var_laplacian']:.2f}, Tenengrad = {raw_metrics['focus_tenengrad']:.2f}, Sobel Mean = {raw_metrics['focus_sobel_mean']:.2f}")
    print(f"    2. Brightness / Exposure : Mean = {raw_metrics['brightness_mean']:.2f}, Median = {raw_metrics['brightness_median']:.2f}, Bright Pixels = {raw_metrics['brightness_bright_pct']:.2f}%, Dark Pixels = {raw_metrics['brightness_dark_pct']:.2f}%")
    print(f"    3. Contrast              : RMS = {raw_metrics['contrast_rms']:.2f}, Michelson = {raw_metrics['contrast_michelson']:.4f}, Gray Std = {raw_metrics['contrast_grayscale_std']:.2f}")
    print(f"    4. Noise Level           : Residual Std = {raw_metrics['noise_residual_std']:.3f}, Decoupled Std = {raw_metrics['noise_decoupled_std']:.3f}, Local Var Mean = {raw_metrics['noise_local_var_mean']:.2f}")
    print(f"    5. Field of View (FOV)   : Coverage = {raw_metrics['fov_coverage']:.4f}, Circularity = {raw_metrics['fov_circularity']:.4f}, Retinal Area = {raw_metrics['fov_retinal_area']:,} px")
    print(f"    6. Illumination          : CoV = {raw_metrics['illum_map_cov']:.4f}, Center/Edge Ratio = {raw_metrics['illum_center_edge_ratio']:.3f}, Center Mean = {raw_metrics['illum_center_mean']:.1f}, Edge Mean = {raw_metrics['illum_edge_mean']:.1f}")
    print(f"    7. Artifacts / Glare     : Glare Blobs = {raw_metrics['artifact_glare_blob_count']}, Max Blob Area = {raw_metrics['artifact_glare_max_area']} px, Saturation = {raw_metrics['artifact_sat_pixel_pct']:.3f}%")

    print("\n  NORMALIZED QUALITY SCORES [0.000, 1.000]:")
    orig_scores = pipeline_res['original_scores']
    print(f"    Focus Score              : {orig_scores['focus']:.4f}")
    print(f"    Brightness Score         : {orig_scores['brightness']:.4f}")
    print(f"    Contrast Score           : {orig_scores['contrast']:.4f}")
    print(f"    Noise Score              : {orig_scores['noise']:.4f}")
    print(f"    FOV Score                : {orig_scores['fov']:.4f}")
    print(f"    Illumination Score       : {orig_scores['illumination']:.4f}")
    print(f"    Artifact Score           : {orig_scores['artifact']:.4f}")
    print(f"    --> Composite Score      : {pipeline_res['original_overall_score']:.4f}")

    print("\n  TRIAGE & ENHANCEMENT DECISIONS:")
    print(f"    Original Status          : {pipeline_res['original_status']}")
    print(f"    Original Hard Failure    : {pipeline_res['original_hard_failure']} ({pipeline_res['original_hard_failure_reasons']})")
    print(f"    Enhancement Required     : {pipeline_res['enhancement_required']}")
    print(f"    Enhancement Applied      : {pipeline_res['enhancement_applied']}")
    ops_applied = pipeline_res['enhancement_operations']
    ops_str = '; '.join(ops_applied) if ops_applied else "None (Bypassed / Not Required)"
    print(f"    Enhancement Operations   : {ops_str}")

    if pipeline_res['enhancement_applied']:
        print(f"    Post-Enhancement Status  : {pipeline_res['post_enhancement_status']}")
        print(f"    Post-Enhancement Score   : {pipeline_res['post_enhancement_overall_score']:.4f}")
        print(f"    Score Delta (Delta)      : {pipeline_res['score_delta']:+.4f}")
        print(f"    Degradation Detected     : {pipeline_res['degradation_detected']}")

    print("\n  FINAL CLINICAL DIRECTIVE & FLAGS:")
    print(f"    Final Status             : {pipeline_res['final_status']}")
    print(f"    Final Directive          : {pipeline_res['final_directive']}")
    
    # Flags explicitly requested by prompt
    flag_ok = pipeline_res['ok_to_go']
    flag_recap = pipeline_res['recapture_required']
    flag_enh = (pipeline_res['final_status'] == 'BORDERLINE')
    print(f"    OK_TO_GO                 : {flag_ok}")
    print(f"    RECAPTURE_REQUIRED       : {flag_recap}")
    print(f"    ENHANCEMENT_REQUIRED     : {flag_enh}")
    print(f"    Decision Rationale       : {pipeline_res['reason']}")
    print("-" * 80)

    # -------------------------------------------------------------
    # 5. VERIFY MODULE 1 ARCHITECTURAL INVARIANTS & IMMUTABILITY
    # -------------------------------------------------------------
    print("\n[Step 5/5] Verifying Module 1 runtime invariants & safety...")

    invariants_passed = True
    invariant_errors = []

    # Invariant 1: Score range checks [0.0, 1.0]
    for dim_name, score in orig_scores.items():
        if not (0.0 <= score <= 1.0):
            invariants_passed = False
            invariant_errors.append(f"Dimension {dim_name} score out of range: {score}")

    comp_score = pipeline_res['original_overall_score']
    if not (0.0 <= comp_score <= 1.0):
        invariants_passed = False
        invariant_errors.append(f"Composite score out of range: {comp_score}")

    # Invariant 2: Mutually exclusive clinical action flags
    final_status = pipeline_res['final_status']
    if final_status == 'CRITICAL':
        if not (flag_ok is False and flag_recap is True and flag_enh is False):
            invariants_passed = False
            invariant_errors.append(f"CRITICAL invariant violation: ok={flag_ok}, recap={flag_recap}, enh={flag_enh}")
    elif final_status == 'BORDERLINE':
        if not (flag_ok is False and flag_recap is False and flag_enh is True):
            invariants_passed = False
            invariant_errors.append(f"BORDERLINE invariant violation: ok={flag_ok}, recap={flag_recap}, enh={flag_enh}")
    elif final_status == 'NON-CRITICAL':
        if not (flag_ok is True and flag_recap is False and flag_enh is False):
            invariants_passed = False
            invariant_errors.append(f"NON-CRITICAL invariant violation: ok={flag_ok}, recap={flag_recap}, enh={flag_enh}")
    else:
        invariants_passed = False
        invariant_errors.append(f"Invalid final status value: {final_status}")

    # Invariant 3: Critical and Non-critical bypass invariant
    if pipeline_res['original_status'] == 'CRITICAL' and pipeline_res['enhancement_applied']:
        invariants_passed = False
        invariant_errors.append("CRITICAL image was improperly enhanced")
    if pipeline_res['original_status'] == 'NON-CRITICAL' and pipeline_res['enhancement_applied']:
        invariants_passed = False
        invariant_errors.append("NON-CRITICAL image was improperly enhanced")

    # Invariant 4: Weights sum to 1.0
    weight_sum = sum(cfg.QUALITY_WEIGHTS.values())
    if abs(weight_sum - 1.0) > 1e-6:
        invariants_passed = False
        invariant_errors.append(f"Weights do not sum to 1.0: {weight_sum}")

    # Invariant 5: Dataset immutability check
    post_stat = os.stat(candidate_path)
    if post_stat.st_size != initial_size or post_stat.st_mtime != initial_mtime:
        invariants_passed = False
        invariant_errors.append(f"Dataset file was modified during run: {candidate_path}")

    if not invariants_passed:
        print("  [FAIL] Invariant checks failed:")
        for err in invariant_errors:
            print(f"    - {err}")
        sys.exit(1)
    else:
        print("  [OK] Invariant 1: All normalized dimension scores and composite score are bounded in [0.0, 1.0].")
        print("  [OK] Invariant 2: Clinical flags (OK_TO_GO, RECAPTURE_REQUIRED, ENHANCEMENT_REQUIRED) are strictly consistent.")
        print("  [OK] Invariant 3: Enhancement routing safety strictly respected (no bypass violations).")
        print("  [OK] Invariant 4: Quality weights sum to exactly 1.000.")
        print("  [OK] Invariant 5: Dataset immutability verified (zero file modifications).")

    print("\n" + "=" * 80)
    print("MODULE 1 SMOKE TEST: PASS")
    print("=" * 80)


if __name__ == '__main__':
    main()
