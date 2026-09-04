"""
Generate reports/representative_quality_audit.csv with exactly 30 images.
"""
import sys
sys.path.insert(0, '.')
import pandas as pd
from src.quality_classifier import classify_fundus_image_quality

df = pd.read_csv('reports/dataset_analysis.csv')

selected_list = [
    # 1. Very Good (5)
    ('Very Good', 'aptos_906d02fb822d.png', 'Optimal sharpness, balanced exposure, clean ocular media, pristine FOV'),
    ('Very Good', 'aptos_a4012932e18d.png', 'Crisp vascular detail, uniform illumination, zero glare, high gradability'),
    ('Very Good', 'train_IDRiD_034.jpg', 'High-resolution (12.2MP) pristine fundus with sharp fovea and optic disc'),
    ('Very Good', 'test_IDRiD_086.jpg', 'Optimal diagnostic exposure, crisp vessel margins, excellent contrast'),
    ('Very Good', 'aptos_6cffc6c6851a.png', 'Standard clinical reference image, optimal tonal distribution and sharpness'),

    # 2. Very Blurry (5)
    ('Very Blurry', 'aptos_164cd5a3a6cd.png', 'Severe optical defocus; fine capillaries and arcade margins completely lost'),
    ('Very Blurry', 'aptos_1f543a86c4d4.png', 'Severe motion/defocus blur; optic disc and vessel tree submerged'),
    ('Very Blurry', 'aptos_a3bd2e034614.png', 'Extreme defocus blur; gradient energy well below diagnostic threshold'),
    ('Very Blurry', 'aptos_6a244e855d0e.png', 'Severe optical blur combined with diffuse overexposure'),
    ('Very Blurry', 'aptos_85fce24084da.png', 'Moderate-to-severe defocus blur requiring edge enhancement or recapture'),

    # 3. Very Dark / Underexposed (5)
    ('Very Dark / Underexposed', 'aptos_77baa08a1345.png', 'Darkest image in dataset; retinal signal submerged below sensor floor'),
    ('Very Dark / Underexposed', 'aptos_b6304c545f95.png', 'Severe underexposure; 19.4% clipped dark pixels, ungradable macula'),
    ('Very Dark / Underexposed', 'aptos_4a7dc013e802.png', 'Severe underexposure; 22.0% dark pixels, lost posterior pole detail'),
    ('Very Dark / Underexposed', 'aptos_417f408ee8e0.png', 'Severe underexposure; mean intensity 30.1, hard failure triggered'),
    ('Very Dark / Underexposed', 'aptos_66460ecab347.png', 'Severe underexposure (Retinal Mean=37.1 < 40.0); signal floor failure, hard failure triggered'),

    # 4. Very Bright / Overexposed (5)
    ('Very Bright / Overexposed', 'aptos_89ee1fa16f90.png', 'Extreme flash bleaching (Mean=153.7); blanched background and washed fovea'),
    ('Very Bright / Overexposed', 'aptos_3c326543fff6.png', 'Severe overexposure (Mean=145.2); attenuated contrast from excess illumination'),
    ('Very Bright / Overexposed', 'aptos_cd29c88c9e36.png', 'Severe overexposure (Mean=141.5); washed nerve fiber layer and retinal reflex'),
    ('Very Bright / Overexposed', 'aptos_aa6242f9e08c.png', 'Severe overexposure with saturation (Mean=140.8, BrightPct=0.30%)'),
    ('Very Bright / Overexposed', 'train_IDRiD_078.jpg', 'Mild overexposure (Mean=130.6); borderline candidate for highlight compression'),

    # 5. Low Contrast / Noisy / Uneven Illumination (5)
    ('Low Contrast / Noisy / Uneven Illumination', 'aptos_e65a2ff90494.png', 'Lowest contrast in dataset (RMS=7.23); dense cataract/corneal haze simulation'),
    ('Low Contrast / Noisy / Uneven Illumination', 'aptos_f86d1c404acb.png', 'Highest high-frequency grain in dataset (Noise Std=2.938, LocalVar=24.68)'),
    ('Low Contrast / Noisy / Uneven Illumination', 'aptos_6ccfdb031184.png', 'Highest illumination CoV in dataset (0.697); severe quadrant shadow failure'),
    ('Low Contrast / Noisy / Uneven Illumination', 'aptos_50d8a8fb7737.png', 'Highest center-to-edge ratio in dataset (1.948); extreme peripheral blackout'),
    ('Low Contrast / Noisy / Uneven Illumination', 'aptos_b69c224edd6e.png', 'Moderate uneven illumination / vignetting (CoV=0.384), candidate for flat-field'),

    # 6. Artifact / FOV Problem Cases (5)
    ('Artifact / FOV Problem', 'aptos_345b1f0abbba.png', 'Severe corneal flash reflection artifact (Sat=1.00%, 5 glare blobs)'),
    ('Artifact / FOV Problem', 'aptos_15cc2aef772a.png', 'Multiple specular reflection glare blobs (15 blobs across retinal field)'),
    ('Artifact / FOV Problem', 'aptos_913490237ad4.png', 'Corneal reflection artifact cluster (Sat=0.99%, 5 glare blobs, Hard Failure)'),
    ('Artifact / FOV Problem', 'aptos_f18abfa690ab.png', 'Lowest circularity in dataset (0.812); boundary distortion from non-circular crop'),
    ('Artifact / FOV Problem', 'aptos_6cb96a6fb029.png', 'Lowest FOV coverage in dataset (47.6%) due to circular camera aperture in 4:3 frame')
]

rows = []
for cat, fn, desc in selected_list:
    matches = df[df['filename'] == fn]
    if len(matches) == 0:
        print(f"ERROR: {fn} not found in dataset_analysis.csv!")
        continue
    r = matches.iloc[0]
    res = classify_fundus_image_quality(r.to_dict())
    
    # Identify detected problems
    problems = []
    if res['score_focus'] < 0.65:
        problems.append(f"Focus Deficit (score={res['score_focus']:.2f}, Lap={r['focus_var_laplacian']:.1f})")
    if res['score_brightness'] < 0.65:
        problems.append(f"Exposure Deficit (score={res['score_brightness']:.2f}, Mean={r['brightness_mean']:.1f})")
    if res['score_contrast'] < 0.65:
        problems.append(f"Contrast Deficit (score={res['score_contrast']:.2f}, RMS={r['contrast_rms']:.1f})")
    if res['score_noise'] < 0.65:
        problems.append(f"High Noise (score={res['score_noise']:.2f}, Std={r['noise_residual_std']:.2f})")
    if res['score_fov'] < 0.85:
        problems.append(f"FOV Deficit (score={res['score_fov']:.2f}, Circ={r['fov_circularity']:.2f})")
    if res['score_illumination'] < 0.65:
        problems.append(f"Illumination Deficit (score={res['score_illumination']:.2f}, CoV={r['illum_map_cov']:.2f})")
    if res['score_artifact'] < 0.65:
        problems.append(f"Artifact Glare (score={res['score_artifact']:.2f}, Sat={r['artifact_sat_pixel_pct']:.2f}%)")
        
    prob_str = "; ".join(problems) if problems else "None (Optimal quality across all 7 dimensions)"
    
    # Specific reason for classification
    if res['is_hard_failure']:
        class_reason = f"HARD FAILURE: {res['hard_failure_reasons']}"
    elif res['status'] == 'NON-CRITICAL':
        class_reason = f"Composite score ({res['overall_score']:.3f} >= 0.70) and all critical dimensions >= 0.35"
    elif res['status'] == 'BORDERLINE':
        class_reason = f"Intermediate composite score ({res['overall_score']:.3f} in [0.50, 0.70]) or sub-0.35 dimension in otherwise viable image"
    else:
        class_reason = f"Composite score ({res['overall_score']:.3f} < 0.50) without hard failure"

    rows.append({
        'category': cat,
        'filename': fn,
        'description': desc,
        'overall_score': res['overall_score'],
        'score_focus': res['score_focus'],
        'score_brightness': res['score_brightness'],
        'score_contrast': res['score_contrast'],
        'score_noise': res['score_noise'],
        'score_fov': res['score_fov'],
        'score_illumination': res['score_illumination'],
        'score_artifact': res['score_artifact'],
        'detected_problems': prob_str,
        'hard_failure': res['is_hard_failure'],
        'hard_failure_reasons': res['hard_failure_reasons'],
        'status': res['status'],
        'directive': res['action'],
        'ok_to_go': res['status'] == 'NON-CRITICAL',
        'recapture_required': res['status'] == 'CRITICAL',
        'classification_reason': class_reason
    })

audit_df = pd.DataFrame(rows)
print(f"Successfully evaluated exactly {len(audit_df)} representative images.")
print(audit_df['category'].value_counts())
audit_df.to_csv('reports/representative_quality_audit.csv', index=False)
print("Saved reports/representative_quality_audit.csv")
