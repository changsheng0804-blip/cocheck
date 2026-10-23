"""本地向量模型（sentence-transformers 能加载的都行，默认 google/embeddinggemma-2，文/图/音同一空间）。
配置：{"type": "local_embed", "model": "google/embeddinggemma-2", "device": "auto|mps|cuda|cpu", "offline": true}"""
import os
from .base import Provider


class LocalEmbed(Provider):
    caps = ('embed',)

    def __init__(self, name, **cfg):
        super().__init__(name, **cfg); self._m = None

    def _model(self):
        if self._m is None:
            if self.cfg.get('offline', True): os.environ.setdefault('HF_HUB_OFFLINE', '1')
            import torch
            from sentence_transformers import SentenceTransformer
            dev = self.cfg.get('device', 'auto')
            if dev == 'auto': dev = 'mps' if torch.backends.mps.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu'
            self.cfg['device'] = dev
            self._m = SentenceTransformer(self.cfg.get('model', 'google/embeddinggemma-2'), device=dev,
                                          model_kwargs={'torch_dtype': torch.float32})
        return self._m

    def embed(self, inputs, prompt=None, image_tokens=None):
        pk = {'image': {'max_soft_tokens': image_tokens}} if image_tokens else None
        return self._model().encode(list(inputs), prompt_name=prompt, normalize_embeddings=True, batch_size=8,
                                    convert_to_numpy=True, processing_kwargs=pk)

    def ping(self):
        self._model(); return {'ok': True, 'device': self.cfg['device']}
