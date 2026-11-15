; Custom NSIS uninstaller hooks for RailWatch 12306.
; Adds an opt-in checkbox during interactive uninstall (skipped during auto-updates)
; so runtime data, Chrome login profile, Electron state, and updater cache can be removed cleanly.

!ifdef BUILD_UNINSTALLER
  Var RailWatchDeleteDataDialog
  Var RailWatchDeleteDataCheckbox
  Var RailWatchDeleteDataState

  !macro customUnWelcomePage
    !insertmacro MUI_UNPAGE_WELCOME
    UninstPage custom un.RailWatchDeleteDataPageCreate un.RailWatchDeleteDataPageLeave

    Function un.RailWatchDeleteDataPageCreate
      ${if} ${isUpdated}
        Abort
      ${endif}

      !insertmacro MUI_HEADER_TEXT "卸载选项" "选择是否同时删除本机保存的数据与登录缓存"
      nsDialogs::Create 1018
      Pop $RailWatchDeleteDataDialog
      ${If} $RailWatchDeleteDataDialog == error
        Abort
      ${EndIf}

      ${NSD_CreateCheckbox} 0u 8u 100% 14u "同时删除本地配置、12306 登录数据与更新缓存"
      Pop $RailWatchDeleteDataCheckbox
      ${If} $RailWatchDeleteDataState == ${BST_CHECKED}
        ${NSD_SetState} $RailWatchDeleteDataCheckbox ${BST_CHECKED}
      ${Else}
        ${NSD_SetState} $RailWatchDeleteDataCheckbox ${BST_UNCHECKED}
      ${EndIf}

      ${NSD_CreateLabel} 12u 28u 94% 52u "勾选后将永久删除 %LOCALAPPDATA%\railwatch-12306（运行配置、Chrome 登录状态、订单记录、日志及窗口状态）、更新缓存及旧版残留数据；不会取消官方订单。若计划稍后重装并保留登录状态，请保持不勾选。"
      Pop $0

      nsDialogs::Show
    FunctionEnd

    Function un.RailWatchDeleteDataPageLeave
      ${NSD_GetState} $RailWatchDeleteDataCheckbox $RailWatchDeleteDataState
    FunctionEnd
  !macroend

  !macro customUnInstall
    ${ifNot} ${isUpdated}
      StrCpy $R2 "0"
      ${if} $RailWatchDeleteDataState == ${BST_CHECKED}
        StrCpy $R2 "1"
      ${else}
        ClearErrors
        ${GetParameters} $R0
        ${GetOptions} $R0 "--delete-app-data" $R1
        ${ifNot} ${Errors}
          StrCpy $R2 "1"
        ${endif}
      ${endif}

      ${if} $R2 == "1"
        ${if} $installMode == "all"
          SetShellVarContext current
        ${endif}
        RMDir /r "$LOCALAPPDATA\railwatch-12306"
        RMDir /r "$LOCALAPPDATA\railwatch-12306-electron-updater"
        RMDir /r "$APPDATA\railwatch-12306-electron"
        ${if} $installMode == "all"
          SetShellVarContext all
        ${endif}
      ${endif}
    ${endif}
  !macroend
!endif
