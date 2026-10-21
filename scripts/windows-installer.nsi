Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!define PRODUCT_NAME "MxinspireX"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\LangjuAgent"
Name "${PRODUCT_NAME}"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\LangjuAgent"
InstallDirRegKey HKCU "Software\LangjuAgent" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "${PRODUCT_NAME}"
Icon "${APP_ICON}"
UninstallIcon "${APP_ICON}"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=2052 "FileDescription" "${PRODUCT_NAME} 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "LegalCopyright" "灵矩绘境"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\LangjuAgent.exe"
!define MUI_FINISHPAGE_RUN_TEXT "启动 ${PRODUCT_NAME}"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "此安装包需要 64 位 Windows。"
    Abort
  ${EndIf}
  SetShellVarContext current
FunctionEnd

!macro CheckAppClosed
  IfFileExists "$INSTDIR\LangjuAgent.exe" 0 +7
    ClearErrors
    FileOpen $0 "$INSTDIR\LangjuAgent.exe" a
    IfErrors 0 +3
      MessageBox MB_OK|MB_ICONEXCLAMATION "请先退出 ${PRODUCT_NAME}，再安装或卸载。"
      Abort
    FileClose $0
!macroend

Section "${PRODUCT_NAME}" SEC_APP
  !insertmacro CheckAppClosed
  SetOutPath "$INSTDIR"
  File /r "${APP_DIR}/*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortcut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\LangjuAgent.exe"
  CreateShortcut "$SMPROGRAMS\${PRODUCT_NAME}\卸载.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\LangjuAgent.exe"
  WriteRegStr HKCU "Software\LangjuAgent" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "灵矩绘境"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\LangjuAgent.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  !insertmacro CheckAppClosed
  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\卸载.lnk"
  RMDir "$SMPROGRAMS\${PRODUCT_NAME}"
  ; Only remove shipped files; never recursively delete a user-selected folder.
  !include "${UNINSTALL_FILES}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  DeleteRegKey HKCU "Software\LangjuAgent"
SectionEnd
