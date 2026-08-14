"""Lightweight exact identities for the ESMFold2 engine boundary."""

from __future__ import annotations


ESM_SDK_REVISION = "917af90b624535eed1e072d343c717e3ec11fef4"
TRANSFORMERS_REVISION = "ef32577f55da19a4989cd7b22e004dc43a4998cb"
TRANSFORMERS_ESMFOLD2_SOURCE_SHA256 = {
    "models/esmfold2/configuration_esmfold2.py": (
        "417d7419d501e7706f715dbfd9b30b61d099c2a16db4bbd15bd322b4bbd52471"
    ),
    "models/esmfold2/modeling_esmfold2.py": (
        "3c36128a70a063aab1278ea2ed1bafbe97787e4c8f5e69639dfb399c96c3f38c"
    ),
}
REMOTE_ESMFOLD2_MODEL = "esmfold2-fast-2026-05"
LOCAL_ESMFOLD2_MODEL = "biohub/ESMFold2"
LOCAL_ESMFOLD2_REVISION = "1ebf0e3481a5184eb6171d40615c79e384b48796"
LOCAL_ESMC_MODEL = "biohub/ESMC-6B"
LOCAL_ESMC_REVISION = "45b0fa5d7fb06faefbd5e3b89bdcef35d564e79a"
LOCAL_DEVICE = "cpu"
LOCAL_TORCH_VERSION = "2.13.0"
LOCAL_ESMFOLD2_ARTIFACT_SHA256 = {
    "ccd.pkl": "9ff44b1927c6b9198e38ffe0928706827a09a350c15530beeeabebfa88038fc5",
    "config.json": "e9ec2496ec433a1dce18627ed4bf3785b4ce0c1d69e4bb4663dad1ab895da012",
    "model.safetensors": (
        "138fd4350d6892b81ce6be7ff9bf5a93ae9d4d3751f46a27438a3f9f0dcefa0e"
    ),
}
LOCAL_ESMC_ARTIFACT_SHA256 = {
    "config.json": "c5566fab6a17fd674141331fe75de917b7904d99fb7a410d2b1593c21e576913",
    "model.safetensors.index.json": (
        "6846456e20e6ee2c37461f7bfc21d316d69bdaf165b925691afcb39e583244da"
    ),
    "model-00001-of-00006.safetensors": (
        "bd90149ff223e6ac1a0cac6147a5ae0df20d3a21df4f65356a1f19cd14f4aa8a"
    ),
    "model-00002-of-00006.safetensors": (
        "f75e2144d8269fe2eb4b3e0823fb089b94f176d8024153e85b8fb573a42294fa"
    ),
    "model-00003-of-00006.safetensors": (
        "f699f01ecc9691d9c6470492765fe54b8b5d2e9f277c139e89427433ffdfe0b2"
    ),
    "model-00004-of-00006.safetensors": (
        "46add1b7be098bbfdc3073884851ba3057f1b33ea23a158b650a37007dabd13d"
    ),
    "model-00005-of-00006.safetensors": (
        "1e1cb62f060a34e18f54a31a76683ef888b8cec59e73315f5b31d25d45a1f88c"
    ),
    "model-00006-of-00006.safetensors": (
        "56c73e13ae96e777ce65eee99364056069ef93b646470f352f83c5f1037b1b18"
    ),
    "special_tokens_map.json": (
        "0b7245ec86c8c3aeaf61523ba70dfa79be137e6283f127bd651adc30b4f15c74"
    ),
    "tokenizer.json": (
        "8d3447b278176e65fb3ef0224472927bf5fee3be46ea2bd77fad0111423cee1f"
    ),
    "tokenizer_config.json": (
        "e8d8e40c9f92b334f0272e80bb65ed4043cb9836523cbae899e9859e8cbb8833"
    ),
}
