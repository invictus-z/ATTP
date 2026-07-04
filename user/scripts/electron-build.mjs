// 用 Node 解析 package.json 版本号，把版本直接拼进 electron-builder 的输出目录参数，
// 避免在 Windows cmd 下 $npm_package_version 不展开导致目录名变成字面量（shell 无关）。
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const projectDir = path.join(__dirname, '..') // user/
const pkg = JSON.parse(readFileSync(path.join(projectDir, 'package.json'), 'utf8'))
const outDir = `release/${pkg.version}`

// execSync 走 shell：Windows 下可解析 node_modules/.bin/electron-builder.cmd；
// pnpm 运行本脚本时已把 .bin 加进 PATH，子进程继承。
execSync(`electron-builder --config.directories.output=${outDir}`, {
  cwd: projectDir,
  stdio: 'inherit',
})
