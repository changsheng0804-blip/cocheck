"""本地向量模型（默认 google/embeddinggemma-2，文/图/音同一空间）。
配置：{"type": "local_embed", "model": "google/embeddinggemma-2", "backend": "auto|mlx|torch", "device": "auto|mps|cuda|cpu", "offline": true}

backend=auto：苹果芯片 Mac 且装了 mlx-vlm 就走 MLX（不需要 torch；实测加载 23s→1.3s、每帧快约 25%，
与 torch 嵌入余弦 ≥0.9998），其他机器（Linux/Windows/Intel Mac/CI）走 sentence-transformers + torch。"""
import os, platform, sys
from .base import Provider


def apple_silicon():
    return sys.platform == 'darwin' and platform.machine() == 'arm64'


def pick_backend(want='auto'):
    if want in ('mlx', 'torch'): return want
    if apple_silicon():
        try:
            import mlx_vlm  # noqa: F401
            return 'mlx'
        except Exception: pass
    return 'torch'


class _MLX:
    """mlx-vlm 版，与 SentenceTransformer.encode 同口径：提示词前缀 + 媒体占位符，均值池化 + L2 归一。
    MLX 的 GPU 流绑定线程，加载和推理都放在一个专用线程里（服务的请求来自不同线程）。"""
    def __init__(self, model):
        from concurrent.futures import ThreadPoolExecutor
        self._ex = ThreadPoolExecutor(1); self._ex.submit(self._load, model).result()

    def encode(self, *a, **k):
        return self._ex.submit(self._encode, *a, **k).result()

    def _load(self, model):
        import json
        from huggingface_hub import snapshot_download
        from mlx_vlm import load
        path = model if os.path.isdir(model) else snapshot_download(model, local_files_only=os.environ.get('HF_HUB_OFFLINE') == '1')
        st = os.path.join(path, 'config_sentence_transformers.json')
        self.prompts = json.load(open(st)).get('prompts', {}) if os.path.exists(st) else {}
        self.model, self.proc = load(path); self.tok = self.proc.tokenizer

    def _run(self, inp):
        import mlx.core as mx, numpy as np
        out = self.model(**{k: mx.array(v) for k, v in dict(inp).items()})
        return np.array(out.text_embeds.astype(mx.float32))

    def _encode(self, items, prompt_name=None, max_soft_tokens=None, batch_size=8):
        import numpy as np
        pre = self.prompts.get(prompt_name, '') if prompt_name else ''
        kind = lambda x: 'text' if isinstance(x, str) else ('image' if 'image' in x else 'audio')
        res = [None] * len(items)
        for k in ('text', 'image', 'audio'):
            idx = [n for n, x in enumerate(items) if kind(x) == k]
            for j in range(0, len(idx), batch_size):          # 同类一批；音频批量约快 3 倍
                b = idx[j:j + batch_size]
                if k == 'text':
                    inp = self.tok([pre + items[n] for n in b], return_tensors='np', padding=True)
                elif k == 'image':
                    kw = {'max_soft_tokens': max_soft_tokens} if max_soft_tokens else {}
                    inp = self.proc(text=[pre + '<|image|>'] * len(b), images=[[self._img(items[n]['image'])] for n in b],
                                    return_tensors='np', padding=True, **kw)
                else:
                    inp = self.proc(text=[pre + '<|audio|>'] * len(b), audio=[[items[n]['audio']] for n in b], return_tensors='np', padding=True)
                for n, e in zip(b, self._run(inp)): res[n] = e
        import mlx.core as mx
        mx.clear_cache()  # 释放推理缓存，常驻内存只留权重（约 2.2 GB）
        E = np.stack(res); return E / np.linalg.norm(E, axis=1, keepdims=True)

    @staticmethod
    def _img(x):
        if isinstance(x, str):
            from PIL import Image
            return Image.open(x).convert('RGB')
        return x


class LocalEmbed(Provider):
    caps = ('embed',)

    def __init__(self, name, **cfg):
        super().__init__(name, **cfg); self._m = None

    def _model(self):
        if self._m is None:
            if self.cfg.get('offline', True): os.environ.setdefault('HF_HUB_OFFLINE', '1')
            model = self.cfg.get('model', 'google/embeddinggemma-2')
            self.cfg['backend'] = b = pick_backend(self.cfg.get('backend', 'auto'))
            if b == 'mlx':
                self.cfg['device'] = 'metal'; self._m = _MLX(model)
            else:
                import torch
                from sentence_transformers import SentenceTransformer
                dev = self.cfg.get('device', 'auto')
                if dev == 'auto': dev = 'mps' if torch.backends.mps.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu'
                self.cfg['device'] = dev
                self._m = SentenceTransformer(model, device=dev, model_kwargs={'torch_dtype': torch.float32})
        return self._m

    def embed(self, inputs, prompt=None, image_tokens=None):
        m = self._model()
        if self.cfg['backend'] == 'mlx':
            return m.encode(list(inputs), prompt_name=prompt, max_soft_tokens=image_tokens)
        pk = {'image': {'max_soft_tokens': image_tokens}} if image_tokens else None
        return m.encode(list(inputs), prompt_name=prompt, normalize_embeddings=True, batch_size=8,
                        convert_to_numpy=True, processing_kwargs=pk)

    def ping(self):
        self._model(); return {'ok': True, 'backend': self.cfg['backend'], 'device': self.cfg['device']}
