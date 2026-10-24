import {cpSync,mkdirSync,writeFileSync,chmodSync} from 'node:fs';
import path from 'node:path';

export function packageCli(root, appDir, platform, executable='MxinspireX') {
  const project=platform==='win32'?path.join(appDir,'resources','app'):path.join(appDir,'Contents','Resources','app');
  const cli=path.join(project,'cli');mkdirSync(cli,{recursive:true});
  cpSync(path.join(root,'scripts/mxinspirex.mjs'),path.join(cli,'mxinspirex.mjs'));
  cpSync(path.join(root,'docs/cli.md'),path.join(cli,'README.md'));
  if(platform==='win32'){
    writeFileSync(path.join(appDir,'mxinspirex-cli.cmd'),`@echo off\r\nsetlocal\r\nset ELECTRON_RUN_AS_NODE=1\r\n"%~dp0${executable}.exe" "%~dp0resources\\app\\cli\\mxinspirex.mjs" %*\r\nexit /b %errorlevel%\r\n`);
  }else{
    const launcher=path.join(appDir,'Contents','MacOS','mxinspirex-cli');
    writeFileSync(launcher,`#!/bin/sh\ncli_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nexport ELECTRON_RUN_AS_NODE=1\nexec "$cli_root/MacOS/${executable}" "$cli_root/Resources/app/cli/mxinspirex.mjs" "$@"\n`);
    chmodSync(launcher,0o755);
  }
}
