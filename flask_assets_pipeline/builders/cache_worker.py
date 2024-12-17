from ..builder import BuilderBase
import os
import json
import uuid


CACHE_WORKER_SCRIPT = """
<script>
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('%(worker_url)s');
}
</script>
"""


class CacheServiceWorkerBuilder(BuilderBase):
    def build(self, mapping, ignore_assets):
        urls = self.assets.urls([f for m in mapping.values() for f in m], with_pre=True, resolve=False)
        if self.assets.state.tailwind:
            urls.append(f"{self.assets.state.output_url}/{self.assets.state.tailwind}")
        urls.extend(self.assets.state.cache_worker_urls)
        cache_name = self.assets.state.cache_worker_name or f"assets-{str(uuid.uuid4())[0:8]}"
        out = self.generate(cache_name, urls)
        filename = os.path.join(self.assets.state.output_folder, self.assets.state.cache_worker_filename)
        with open(filename, 'w') as f:
            f.write(out)

    def generate(self, cache_name, urls):
        inject = "".join([
            "/* AUTO-GENERATED SERVICE WORKER */\n\n",
            "const CACHE_NAME = %s;\n" % json.dumps(cache_name),
            "const CACHE_URLS = %s;\n" % json.dumps(urls)
        ])
        template_filename = os.path.join(os.path.dirname(__file__), 'cache-worker.js')
        with open(template_filename) as f:
            lines = f.readlines()
        del lines[0:6]
        lines.insert(0, inject)
        return "".join(lines)