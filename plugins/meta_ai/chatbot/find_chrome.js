const fs = require('fs');
const paths = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    process.env.LOCALAPPDATA + '\\Google\\Chrome\\Application\\chrome.exe',
];
let found = false;
for (const p of paths) {
    if (fs.existsSync(p)) {
        console.log('CHROME_FOUND:' + p);
        found = true;
        break;
    }
}
if (!found) console.log('CHROME_NOT_FOUND');
