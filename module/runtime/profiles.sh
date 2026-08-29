#!/system/bin/sh

# Static reviewed compatibility profiles. Unknown source hashes fail closed.

_otast_role_for_dir() {
  local dir
  case $1 in
    "$ADB_ROOT/modules_update"/*) printf 'staged\n' ;;
    "$ADB_ROOT/modules"/*) printf 'active\n' ;;
    *) return 1 ;;
  esac
}

_otast_plan_exact_file() {
  local id target path mode template allowed required source
  id=$1
  target=$2
  path=$3
  mode=$4
  template=$5
  allowed=$6
  required=${7:-required}
  if [ ! -e "$path" ]; then
    [ "$required" = optional ] && return 0
    otast_stop "required reviewed target path is missing: $path"
    return 1
  fi
  source=$(otast_plan_source_file "$id" "$template") || return 1
  otast_plan_add "$id" "$target" "$path" "$mode" "$source" exact "$allowed"
}

_otast_plan_transformed_file() {
  local id target path mode transform allowed required source
  id=$1
  target=$2
  path=$3
  mode=$4
  transform=$5
  allowed=$6
  required=${7:-required}
  if [ ! -e "$path" ]; then
    [ "$required" = optional ] && return 0
    otast_stop "required reviewed target path is missing: $path"
    return 1
  fi
  [ -f "$path" ] && [ ! -L "$path" ] || {
    otast_stop "reviewed target is not a safe regular file: $path"
    return 1
  }
  source=$OTAST_TMP_ROOT/source.$$.${id}
  "$transform" "$path" "$source" || {
    rm -f "$source" 2>/dev/null || :
    otast_stop "reviewed transformation failed: $path"
    return 1
  }
  chmod 0600 "$source" || return 1
  otast_plan_add "$id" "$target" "$path" "$mode" "$source" exact "$allowed"
}

_otast_plan_transformed_external() {
  local id target path mode transform source
  id=$1
  target=$2
  path=$3
  mode=$4
  transform=$5
  [ -f "$path" ] && [ ! -L "$path" ] || {
    otast_stop "required configuration file is missing or unsafe: $path"
    return 1
  }
  source=$OTAST_TMP_ROOT/source.$$.${id}
  "$transform" "$path" "$source" || {
    rm -f "$source" 2>/dev/null || :
    otast_stop "configuration transformation failed: $path"
    return 1
  }
  chmod 0600 "$source" || return 1
  otast_plan_add "$id" "$target" "$path" "$mode" "$source" external ''
}

otast_plan_global_contracts() {
  local source
  source=$(otast_plan_source_text boot-hash <<EOF_BOOT
$OTAST_VBMETA_DIGEST
EOF_BOOT
) || return 1
  otast_plan_add boot-hash platform "$ADB_ROOT/boot_hash" 0644 "$source" external '' || return 1

  if [ "$OTAST_TRICKY_PATCH_POLICY" = ota ] && otast_effective_module_dirs tricky_store | grep -q .; then
    source=$(otast_plan_source_text tricky-security-patch <<EOF_TRICKY
system=prop
boot=$OTAST_SYSTEM_PATCH
vendor=$OTAST_VENDOR_PATCH
EOF_TRICKY
) || return 1
    otast_plan_add tricky-security-patch trickystore "$ADB_ROOT/tricky_store/security_patch.txt" 0644 "$source" external '' || return 1
  fi
}

otast_plan_pif() {
  local dir role source global_planned
  if [ -e "$ADB_ROOT/tricky_store/pif_auto_security_patch" ] || [ -L "$ADB_ROOT/tricky_store/pif_auto_security_patch" ]; then
    otast_stop 'PIF automatic security-patch generation conflicts with OTAST ownership'
    return 1
  fi

  global_planned=0
  for dir in $(otast_effective_module_dirs playintegrityfix); do
    role=$(_otast_role_for_dir "$dir") || return 1

    if [ "$OTAST_PIF_IDENTITY_POLICY" = ota ]; then
      _otast_plan_transformed_file pif-autopif-$role playintegrityfix "$dir/autopif.sh" 0755 \
        otast_transform_pif_autopif \
        '1077b90d7e5ff7191ae7d9238c7f6eeb121470aed249a1b0d083366d04e589b1,67d456a70f6195a9b423e28859845b7fd42dd1bb3bec8596f45f55fe0d492a4a,04192e43776fb23ff0e132da0f2cb07e99ac0c243d785ace100a64d4ddecd213' || return 1

      _otast_plan_transformed_file pif-autopif-ota-$role playintegrityfix "$dir/autopif_ota.sh" 0755 \
        otast_transform_pif_ota \
        'cf26c37ae06524e557e4bd6e9262c965ad2c52e93d5d027a0f027933373751d1' || return 1
    fi

    _otast_plan_transformed_external pif-prop-$role playintegrityfix "$dir/pif.prop" 0644 \
      otast_transform_pif_prop || return 1

    if [ "$global_planned" -eq 0 ]; then
      source=$OTAST_TMP_ROOT/source.$$.pif-global-prop
      if [ -e "$ADB_ROOT/pif.prop" ]; then
        [ -f "$ADB_ROOT/pif.prop" ] && [ ! -L "$ADB_ROOT/pif.prop" ] || {
          otast_stop "unsafe global PIF configuration: $ADB_ROOT/pif.prop"
          return 1
        }
        otast_transform_pif_prop "$ADB_ROOT/pif.prop" "$source" || return 1
      else
        otast_transform_pif_prop "$dir/pif.prop" "$source" || return 1
      fi
      chmod 0600 "$source" || return 1
      otast_plan_add pif-global-prop playintegrityfix "$ADB_ROOT/pif.prop" 0644 "$source" external '' || return 1
      global_planned=1
    fi

    _otast_plan_transformed_file pif-security-patch-$role playintegrityfix "$dir/security_patch.sh" 0755 \
      otast_transform_pif_security_patch \
      'a21fa1444ad870ad2ba09cb2a45a0576361df6062369d13f05fbf0db78f29476' || return 1
  done
}

otast_plan_ta_utl() {
  local id dir role id_tag
  for id in TA_utl .TA_utl; do
    for dir in $(otast_effective_module_dirs "$id"); do
      role=$(_otast_role_for_dir "$dir") || return 1
      case "$id" in
        TA_utl) id_tag=canonical ;;
        .TA_utl) id_tag=hidden ;;
        *) otast_stop "unsupported TA UTL alias: $id"; return 1 ;;
      esac
      _otast_plan_transformed_file ta-prop-$role-$id_tag ta-utl "$dir/prop.sh" 0755 \
        otast_transform_ta_prop \
        'fffa4d98aafb444594480ccaecbdbc083fee8e860418f86cc55e2422dc7a647f' || return 1
    done
  done
}

otast_plan_yurikey() {
  local dir role
  for dir in $(otast_effective_module_dirs Yurikey); do
    role=$(_otast_role_for_dir "$dir") || return 1
    _otast_plan_exact_file yurikey-action-$role yurikey "$dir/action.sh" 0755 "$MODDIR/templates/yurikey/action.sh" \
      'cf2808d234d10cd627bc49b487a4b7884dd6dc4d80f271e23f40061ebcb83682,bdc1b5ae67c94b26fef19e5a461559b81e9c3f345b3d820fbfc17ea8ab87557e' || return 1
    _otast_plan_exact_file yurikey-service-$role yurikey "$dir/service.sh" 0755 "$MODDIR/templates/yurikey/service.sh" \
      '6bc09314d843eb04ba7f682bdb9b03091a061e537dc5acbf80cd5eb339b68756' || return 1
    _otast_plan_exact_file yurikey-target-$role yurikey "$dir/Yuri/target_txt.sh" 0755 "$MODDIR/templates/yurikey/target_txt.sh" \
      '12de2efb87a6763d514a35b291ab08022ffa46dda5d4759c505d905651ef19a9' || return 1
    _otast_plan_exact_file yurikey-boot-hash-$role yurikey "$dir/Yuri/boot_hash.sh" 0755 "$MODDIR/templates/yurikey/apply.sh" \
      'ec9ad40fb5f2df51b5c773f93824f366fa2428b20a827ebd70fc648d7f0585fb' || return 1
    _otast_plan_exact_file yurikey-web-boot-hash-$role yurikey "$dir/webroot/common/boot_hash.sh" 0755 "$MODDIR/templates/yurikey/apply.sh" \
      'ec9ad40fb5f2df51b5c773f93824f366fa2428b20a827ebd70fc648d7f0585fb' || return 1
    _otast_plan_exact_file yurikey-security-patch-$role yurikey "$dir/Yuri/security_patch.sh" 0755 "$MODDIR/templates/yurikey/apply.sh" \
      '21c734e42469164382f3a29989a258cf687bc7fb898c60611791952533c50d10,ebb66e9c1765b62732f7352ba1e2350696feb4b6357a07e1b565622af5a1c786' || return 1
    _otast_plan_exact_file yurikey-pif-$role yurikey "$dir/Yuri/pif.sh" 0755 "$MODDIR/templates/yurikey/apply.sh" \
      'ff7d32e1365ad4007b0e05d709acde8390c9c5de616026e14fb4c47fbe69e83d' optional || return 1
    _otast_plan_exact_file yurikey-clear-$role yurikey "$dir/Yuri/clear_all_detection_traces.sh" 0755 "$MODDIR/templates/yurikey/clear-all.sh" \
      'e0249324a156f163625d7bb1ea141b6baa0d54f7dd54e7df1cac6493c851f861,efd7ae12259efea5640dc5fdd8d950dfbffaf154f7aa78dba9d782335d4c0893' || return 1
    _otast_plan_exact_file yurikey-pif2-$role yurikey "$dir/webroot/common/pif2.sh" 0755 "$MODDIR/templates/yurikey/apply.sh" \
      '8125d05e170e10ac76b20f879fc093fdac576791cf5b058983ea1547d1647677' || return 1
  done
}

otast_plan_vbmeta_fixer() {
  local dir role
  for dir in $(otast_effective_module_dirs vbmeta-fixer); do
    role=$(_otast_role_for_dir "$dir") || return 1
    _otast_plan_exact_file vbmeta-service-$role vbmeta-fixer "$dir/service.sh" 0755 "$MODDIR/templates/vbmeta-fixer/service.sh" \
      '68877fdf5e64fabf3a59ac608097d9ffbf4d770119b7793cf3ddce8951563b42,dbf67cf9d728b8495f843f71c01b51db74845617a3c5e7cbe52591055decc23b' || return 1
  done
}

otast_plan_all() {
  otast_plan_begin || return 1
  otast_plan_global_contracts || return 1
  otast_plan_pif || return 1
  otast_plan_ta_utl || return 1
  otast_plan_yurikey || return 1
  otast_plan_vbmeta_fixer || return 1
  return 0
}
