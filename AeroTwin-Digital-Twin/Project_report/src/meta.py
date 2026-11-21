"""Front-matter details and references for the report."""

REPORT_TYPE = "A Project Phase-I Report on"
TITLE = ("AeroTwin: AI-Based Digital Twin for Health Monitoring and Fault Prediction "
         "of UAV Piston Engines")
BRANCH = "Computer Science and Engineering"
YEAR = "2026-27"
GUIDE = "Mrs. Nitu Pariyal"
HOD = "A. M. Rajurkar"
DIRECTOR = "[Director Name]"
CLASS_DIV = "[Class-Division, e.g. B. Tech-CSE-A]"
STUDENTS = [
    ("Pranjal Shahane", "[Roll No]"),
    ("Vaishnavi Titare", "[Roll No]"),
    ("Vaibhav Mandhani", "[Roll No]"),
    ("Tanishka Adkalatwar", "[Roll No]"),
]


def cert_names() -> str:
    names = [f'<span class="nm">{n}</span>' for n, _ in STUDENTS]
    return ", ".join(names[:-1]) + " and " + names[-1]


ACK = [
    "We are deeply indebted to our project guide, Mrs. Nitu Pariyal, for her valuable guidance, constant "
    "help and encouragement throughout this work. Her suggestions and the many discussions we had with her "
    "shaped both the direction of the project and the quality of this report.",
    "We are thankful to A. M. Rajurkar, Head of the Department of Computer Science and Engineering, MGM's "
    "College of Engineering, Nanded, for providing the facilities and support needed to carry out this "
    "project.",
    "We express our sincere gratitude to [Director Name], Director, MGM's College of Engineering, Nanded, for "
    "the facilities provided by the institute and for the inspiration to undertake this work.",
    "Last but not least, we thank all the teaching and non-teaching staff of the department, our families "
    "and our friends, who helped us directly or indirectly in the completion of this project.",
]

ABSTRACT = [
    "AeroTwin is a real-time digital twin for the piston engine of a Medium Altitude Long Endurance "
    "unmanned aerial vehicle. It combines a physics-based mean-value model of the Rotax 915 iS engine, "
    "held permanently in an as-new condition, with statistical and deep-learning anomaly detectors built "
    "with Python, PyTorch and scikit-learn. Its key capability is detecting gradual engine degradation "
    "before any certified limit is crossed.",
    "Engine telemetry is acquired over a CAN bus and validated at the edge, where certified-limit rules "
    "run independently of the datalink. The twin predicts what a healthy engine would read at the same "
    "operating point, and the residuals are scored by a statistical ensemble, an LSTM autoencoder and a "
    "deep multi-task network whose outputs are fused. Health indices, fault naming, remaining-life "
    "estimation and mission reliability are served through a FastAPI back end to a React console for "
    "commanders, operators, maintainers and engineers.",
    "On forty engines withheld from training, the fused detector reached an alarm precision of 0.996 and a "
    "ROC-AUC of 0.989 with a false-positive rate of about 1 %, and flagged 6,567 degrading windows that "
    "certified limits missed. Each twin update takes 51 ms at the median against a 200 ms budget, and the "
    "onboard model occupies 150 KB. The console provides mission planning, pre-flight checklists, live "
    "comparison with the twin, a three-dimensional fault view and post-flight reports.",
    "Overall, this project showcases how physics and machine learning can be combined into an accurate, "
    "explainable, offline and affordable system for condition-based maintenance of unmanned aircraft "
    "engines.",
]

REFERENCES = [
    ("A. Saxena, K. Goebel, D. Simon and N. Eklund, “Damage propagation modeling for aircraft engine "
     "run-to-failure simulation,” Proc. IEEE International Conference on Prognostics and Health "
     "Management (PHM), 2008.", None),
    ("A. Saxena, J. Celaya, E. Balaban, K. Goebel, B. Saha, S. Saha and M. Schwabacher, “Metrics for "
     "evaluating performance of prognostic techniques,” Proc. IEEE International Conference on "
     "Prognostics and Health Management (PHM), 2008.", None),
    ("F. Tao, H. Zhang, A. Liu and A. Y. C. Nee, “Digital twin in industry: State-of-the-art,” "
     "IEEE Transactions on Industrial Informatics, vol. 15, no. 4, pp. 2405–2415, 2019.", None),
    ("K. I. Shahin and S. Lazarova-Molnar, “Digital twins in prognostics and health management: a "
     "review of diagnostic, remaining useful life and predictive maintenance applications,” IEEE "
     "International Conference on System Reliability and Safety, 2024.", None),
    ("M. Raissi, P. Perdikaris and G. E. Karniadakis, “Physics-informed neural networks: A deep "
     "learning framework for solving forward and inverse problems involving nonlinear partial differential "
     "equations,” Journal of Computational Physics, vol. 378, pp. 686–707, 2019.", None),
    ("R. B. Randall and J. Antoni, “Rolling element bearing diagnostics—A tutorial,” "
     "Mechanical Systems and Signal Processing, vol. 25, no. 2, pp. 485–520, 2011.", None),
    ("J. Antoni, “Fast computation of the kurtogram for the detection of transient faults,” "
     "Mechanical Systems and Signal Processing, vol. 21, no. 1, pp. 108–124, 2007.", None),
    ("D. R. Cox, “Regression models and life-tables,” Journal of the Royal Statistical Society, "
     "Series B, vol. 34, no. 2, pp. 187–220, 1972.", None),
    ("A. N. Angelopoulos and S. Bates, “A gentle introduction to conformal prediction and "
     "distribution-free uncertainty quantification,” arXiv preprint arXiv:2107.07511, 2021.",
     "https://arxiv.org/abs/2107.07511"),
    ("S. Hochreiter and J. Schmidhuber, “Long short-term memory,” Neural Computation, vol. 9, "
     "no. 8, pp. 1735–1780, 1997.", None),
    ("P. Malhotra, A. Ramakrishnan, G. Anand, L. Vig, P. Agarwal and G. Shroff, “LSTM-based "
     "encoder-decoder for multi-sensor anomaly detection,” ICML Workshop on Anomaly Detection, "
     "arXiv:1607.00148, 2016.", "https://arxiv.org/abs/1607.00148"),
    ("Z. He, X. Xu and S. Deng, “Discovering cluster-based local outliers,” Pattern Recognition "
     "Letters, vol. 24, no. 9–10, pp. 1641–1650, 2003.", None),
    ("C.-C. M. Yeh, Y. Zhu, L. Ulanova, N. Begum, Y. Ding, H. A. Dau, D. F. Silva, A. Mueen and E. Keogh, "
     "“Matrix Profile I: All pairs similarity joins for time series,” Proc. IEEE International "
     "Conference on Data Mining (ICDM), 2016.", None),
    ("J. B. Heywood, Internal Combustion Engine Fundamentals, McGraw-Hill, New York, 1988.", None),
    ("D. G. Goodwin, H. K. Moffat and R. L. Speth, “Cantera: An object-oriented software toolkit for "
     "chemical kinetics, thermodynamics, and transport processes,” Cantera Developers, 2017.",
     "https://www.cantera.org"),
    ("L. Prokhorenkova, G. Gusev, A. Vorobev, A. V. Dorogush and A. Gulin, “CatBoost: unbiased "
     "boosting with categorical features,” Advances in Neural Information Processing Systems "
     "(NeurIPS), 2018.", None),
]
