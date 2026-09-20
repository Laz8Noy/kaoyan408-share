import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  // 相对 base：成品挂在 GitHub Pages 子路径（kaoyan408-share/12-…/）下也能取到资源
  base: './',
  plugins: [react()],
  server: {
    port: 5175,
    // Windows 下原子写入的临时文件会让原生 watcher 抛 EBUSY 崩溃；改用轮询保稳
    watch: { usePolling: true, interval: 300 }
  }
});
