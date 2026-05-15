"""Body composition calculator for Xiaomi Body Composition Scale S400.

Ported from mnm-matin/miscale (MIT) with light type cleanup.
Formula heritage: Xiaomi Mi Home app — empirically reverse-engineered.

These formulas approximate what the Mi Home app would show. They are NOT
medical-grade; use only as fitness reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SexLiteral = Literal["male", "female"]


BODY_TYPE_NAMES: list[str] = [
    "obese",
    "overweight",
    "thick-set",
    "lack-exercise",
    "balanced",
    "balanced-muscular",
    "skinny",
    "balanced-skinny",
    "skinny-muscular",
]


@dataclass(frozen=True)
class UserProfile:
    sex: SexLiteral
    age_years: int
    height_cm: int


def _clamp(v: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, v)))


_FAT_PCT_SCALES: list[tuple[int, int, list[float], list[float]]] = [
    (0, 12,  [12.0, 21.0, 30.0, 34.0], [7.0, 16.0, 25.0, 30.0]),
    (12, 14, [15.0, 24.0, 33.0, 37.0], [7.0, 16.0, 25.0, 30.0]),
    (14, 16, [18.0, 27.0, 36.0, 40.0], [7.0, 16.0, 25.0, 30.0]),
    (16, 18, [20.0, 28.0, 37.0, 41.0], [7.0, 16.0, 25.0, 30.0]),
    (18, 40, [21.0, 28.0, 35.0, 40.0], [11.0, 17.0, 22.0, 27.0]),
    (40, 60, [22.0, 29.0, 36.0, 41.0], [12.0, 18.0, 23.0, 28.0]),
    (60, 100,[23.0, 30.0, 37.0, 42.0], [14.0, 20.0, 25.0, 30.0]),
]

_MUSCLE_SCALES: list[tuple[dict, dict]] = [
    ({"male": 170, "female": 160}, {"female": [36.5, 42.6], "male": [49.4, 59.5]}),
    ({"male": 160, "female": 150}, {"female": [32.9, 37.6], "male": [44.0, 52.5]}),
    ({"male": 0,   "female": 0},   {"female": [29.1, 34.8], "male": [38.5, 46.6]}),
]


def _fat_scale_for_age(age: int, sex: SexLiteral) -> list[float]:
    for lo, hi, f, m in _FAT_PCT_SCALES:
        if lo <= age < hi:
            return f if sex == "female" else m
    return _FAT_PCT_SCALES[-1][2] if sex == "female" else _FAT_PCT_SCALES[-1][3]


def _muscle_scale(height_cm: int, sex: SexLiteral) -> list[float]:
    for mins, thresholds in _MUSCLE_SCALES:
        if height_cm >= mins[sex]:
            return thresholds[sex]
    return _MUSCLE_SCALES[-1][1][sex]


def _lbm(height_cm: int, weight_kg: float, age: int, impedance: float) -> float:
    lbm = (height_cm * 9.058 / 100.0) * (height_cm / 100.0)
    lbm += weight_kg * 0.32 + 12.226
    lbm -= impedance * 0.0068
    lbm -= age * 0.0542
    return lbm


def _fat_percent(*, height_cm: int, weight_kg: float, age: int,
                 sex: SexLiteral, impedance: float) -> float:
    adjust = 0.8
    if sex == "female":
        adjust = 9.25 if age <= 49 else 7.25
    lbm = _lbm(height_cm, weight_kg, age, impedance)
    coef = 1.0
    if sex == "male" and weight_kg < 61:
        coef = 0.98
    elif sex == "female" and weight_kg > 60:
        coef = 1.03 if height_cm > 160 else 0.96
    elif sex == "female" and weight_kg < 50:
        coef = 1.03 if height_cm > 160 else 1.02
    fat_pct = (1.0 - (((lbm - adjust) * coef) / weight_kg)) * 100.0
    if fat_pct > 63:
        fat_pct = 75
    return _clamp(fat_pct, 5, 75)


def _water_percent(fat_pct: float) -> float:
    water = (100.0 - fat_pct) * 0.7
    coef = 1.02 if water <= 50 else 0.98
    if water * coef >= 65:
        water = 75
    return _clamp(water * coef, 35, 75)


def _bmi(height_cm: int, weight_kg: float) -> float:
    h = height_cm / 100.0
    return _clamp(weight_kg / (h * h), 10, 90)


def _bmr(height_cm: int, weight_kg: float, age: int, sex: SexLiteral) -> float:
    if sex == "male":
        bmr = 877.8 + (weight_kg * 14.916) - (height_cm * 0.726) - (age * 8.976)
        if bmr > 2322:
            bmr = 5000
    else:
        bmr = 864.6 + (weight_kg * 10.2036) - (height_cm * 0.39336) - (age * 6.204)
        if bmr > 2996:
            bmr = 5000
    return _clamp(bmr, 500, 10000)


def _ideal_weight(height_cm: int, sex: SexLiteral) -> float:
    return (height_cm - 80) * 0.7 if sex == "male" else (height_cm - 70) * 0.6


def _metabolic_age(height_cm: int, weight_kg: float, age: int,
                   impedance: float, sex: SexLiteral) -> float:
    if sex == "male":
        ma = (height_cm * -0.7471 + weight_kg * 0.9161 + age * 0.4184
              + impedance * 0.0517 + 54.2267)
    else:
        ma = (height_cm * -1.1165 + weight_kg * 1.5784 + age * 0.4615
              + impedance * 0.0415 + 83.2548)
    return _clamp(ma, 15, 80)


def _visceral_fat(height_cm: int, weight_kg: float, age: int, sex: SexLiteral) -> float:
    if sex == "female":
        if weight_kg > (13 - (height_cm * 0.5)) * -1:
            sub2 = ((height_cm * 1.45) + (height_cm * 0.1158) * height_cm) - 120
            sub  = weight_kg * 500 / sub2
            vf = (sub - 6) + (age * 0.07)
        else:
            sub = 0.691 + (height_cm * -0.0024) + (height_cm * -0.0024)
            vf = (((height_cm * 0.027) - (sub * weight_kg)) * -1) + (age * 0.07) - age
    elif height_cm < weight_kg * 1.6:
        sub = ((height_cm * 0.4) - (height_cm * (height_cm * 0.0826))) * -1
        vf = ((weight_kg * 305) / (sub + 48)) - 2.9 + (age * 0.15)
    else:
        sub = 0.765 + height_cm * -0.0015
        vf = (((height_cm * 0.143) - (weight_kg * sub)) * -1) + (age * 0.15) - 5.0
    return _clamp(vf, 1, 50)


def _bone_mass(height_cm: int, weight_kg: float, age: int,
               impedance: float, sex: SexLiteral) -> float:
    lbm = _lbm(height_cm, weight_kg, age, impedance)
    base = 0.245691014 if sex == "female" else 0.18016894
    bm = (base - (lbm * 0.05158)) * -1
    bm = bm + 0.1 if bm > 2.2 else bm - 0.1
    if sex == "female" and bm > 5.1:
        bm = 8
    elif sex == "male" and bm > 5.2:
        bm = 8
    return _clamp(bm, 0.5, 8)


def _muscle_mass(weight_kg: float, fat_pct: float,
                 bone_mass: float, sex: SexLiteral) -> float:
    mm = weight_kg - ((fat_pct * 0.01) * weight_kg) - bone_mass
    if sex == "female" and mm >= 84:
        mm = 120
    elif sex == "male" and mm >= 93.5:
        mm = 120
    return _clamp(mm, 10, 120)


def _protein_percent(weight_kg: float, muscle_mass: float, water_pct: float) -> float:
    p = (muscle_mass / weight_kg) * 100.0 - water_pct
    return _clamp(p, 5, 32)


def _body_type(age: int, height_cm: int, sex: SexLiteral,
               fat_pct: float, muscle_mass: float) -> int:
    fat_scale = _fat_scale_for_age(age, sex)
    if fat_pct > fat_scale[2]:
        factor = 0
    elif fat_pct < fat_scale[1]:
        factor = 2
    else:
        factor = 1
    muscle = _muscle_scale(height_cm, sex)
    if muscle_mass > muscle[1]:
        return 2 + factor * 3
    if muscle_mass < muscle[0]:
        return factor * 3
    return 1 + factor * 3


def compute(weight_kg: float, impedance_ohm: float, profile: UserProfile) -> dict:
    """Return a dict of computed body composition metrics."""
    fat = _fat_percent(
        height_cm=profile.height_cm, weight_kg=weight_kg,
        age=profile.age_years, sex=profile.sex, impedance=impedance_ohm,
    )
    water = _water_percent(fat)
    bone = _bone_mass(profile.height_cm, weight_kg,
                      profile.age_years, impedance_ohm, profile.sex)
    muscle = _muscle_mass(weight_kg, fat, bone, profile.sex)
    protein = _protein_percent(weight_kg, muscle, water)
    bt_idx = _body_type(profile.age_years, profile.height_cm, profile.sex, fat, muscle)
    return {
        "bmi": round(_bmi(profile.height_cm, weight_kg), 1),
        "ideal_weight_kg": round(_ideal_weight(profile.height_cm, profile.sex), 2),
        "bmr_kcal_day": int(round(_bmr(profile.height_cm, weight_kg,
                                       profile.age_years, profile.sex))),
        "fat_percent": round(fat, 1),
        "water_percent": round(water, 1),
        "protein_percent": round(protein, 1),
        "muscle_mass_kg": round(muscle, 2),
        "bone_mass_kg": round(bone, 2),
        "visceral_fat": round(_visceral_fat(profile.height_cm, weight_kg,
                                            profile.age_years, profile.sex), 2),
        "metabolic_age_years": int(round(_metabolic_age(
            profile.height_cm, weight_kg, profile.age_years,
            impedance_ohm, profile.sex))),
        "body_type": bt_idx + 1,
        "body_type_name": BODY_TYPE_NAMES[bt_idx],
    }
