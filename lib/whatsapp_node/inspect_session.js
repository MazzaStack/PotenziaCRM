// inspect_session.js - Inspecciona los archivos de sesión para encontrar contactos
const fs = require('fs');
const path = require('path');
const os = require('os');

const usuario = 'GermanMazza';
const sessionDir = path.join(os.homedir(), `.whatsapp_bot_session_${usuario}`);

console.log('Session dir:', sessionDir);

const files = fs.readdirSync(sessionDir);
console.log('Total files:', files.length);

// Categorize
const byType = {};
files.forEach(f => {
    const prefix = f.split('-')[0];
    byType[prefix] = (byType[prefix] || 0) + 1;
});
console.log('\nFile types:');
Object.entries(byType).sort((a,b) => b[1]-a[1]).forEach(([k,v]) => console.log(`  ${k}: ${v}`));

// Look for contact-related files
const contactFiles = files.filter(f => f.startsWith('contact') || f.includes('roster') || f.includes('contacts'));
console.log('\nContact files:', contactFiles.slice(0, 10));

// Look for pre-key or sender-key files with phone numbers
const phoneFiles = files.filter(f => /\d{7,}@s/.test(f));
console.log('\nFiles with @s.whatsapp.net phone JIDs (sample):', phoneFiles.slice(0, 5));

// Try to read a sender-key file
const skFiles = files.filter(f => f.startsWith('sender-key'));
if (skFiles.length > 0) {
    console.log('\nSample sender-key file:', skFiles[0]);
    try {
        const data = JSON.parse(fs.readFileSync(path.join(sessionDir, skFiles[0]), 'utf8'));
        console.log('  Content:', JSON.stringify(data).slice(0, 200));
    } catch(e) {}
}

// Most important: look for app-state sync files which have contact lists
const appStateFiles = files.filter(f => f.includes('app-state') || f.startsWith('app'));
console.log('\nApp state files:', appStateFiles.slice(0, 5));

// Check for any JSON file with phone numbers
const allPhoneJids = new Set();
const checkFiles = files.filter(f => f.endsWith('.json')).slice(0, 100);
checkFiles.forEach(f => {
    try {
        const content = fs.readFileSync(path.join(sessionDir, f), 'utf8');
        const matches = content.match(/\d{7,15}@s\.whatsapp\.net/g);
        if (matches) matches.forEach(m => allPhoneJids.add(m));
    } catch(e) {}
});
console.log('\nPhone JIDs found in first 100 JSON files:', allPhoneJids.size);
if (allPhoneJids.size > 0) {
    console.log('Sample:', [...allPhoneJids].slice(0, 5));
}
