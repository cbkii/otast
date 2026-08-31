import{t as e}from"./dist-lcs5aYiW.js";import{d as t,l as n}from"./main-DnoTvuZO.js";var r=document.getElementById(`boot-hash-dialog`),i=document.getElementById(`boot-hash-input`),a=document.getElementById(`boot-hash-save-button`),o=document.getElementById(`cancel-boot-hash`);window.trimInput=e=>{e.value=e.value.replace(/\s+/g,``).toLowerCase()},document.getElementById(`boot-hash`).addEventListener(`click`,async()=>{r.show(),e(`sed '/[^#]/d; /^$/d' /data/adb/boot_hash`).then(({errno:e,stdout:t})=>{e===0?i.value=t.trim()||``:i.value=``})}),a.addEventListener(`click`,async()=>{let a=i.value.trim();e(`
        resetprop -n ro.boot.vbmeta.digest "${a}"
        [ -z "${a}" ] && rm -f /data/adb/boot_hash || {
            echo "${a}" > /data/adb/boot_hash
            chmod 644 /data/adb/boot_hash
        }
        resetprop -c || true
    `,{env:{PATH:`$PATH:/data/adb/ksu/bin:/data/adb/ap/bin:/data/adb/magisk`}}).then(()=>{n(t(`prompt_boot_hash_set`)),r.close()})}),o.addEventListener(`click`,()=>{r.close()}),i.addEventListener(`keydown`,e=>{e.key===`Enter`&&a.click()});