"""
Test vignetting rule on key cases.
"""
import pandas as pd
df = pd.read_csv('reports/dataset_analysis.csv')
cases = ['train_IDRiD_352.jpg', 'aptos_5cab3ef4b31c.png', 'aptos_50d8a8fb7737.png', 'aptos_6ccfdb031184.png']
sub = df[df['filename'].isin(cases)]
for _, r in sub.iterrows():
    cond_old = (r.illum_center_edge_ratio > 1.75) or (r.illum_map_cov > 0.52)
    cond_new = ((r.illum_center_edge_ratio > 1.75) and (r.illum_map_cov > 0.45)) or (r.illum_map_cov > 0.52)
    print(f"{r.filename}: Ratio={r.illum_center_edge_ratio:.3f}, CoV={r.illum_map_cov:.3f} | Old HF={cond_old} | New HF={cond_new}")
