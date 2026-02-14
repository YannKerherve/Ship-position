import type { ExternalPluginConfig } from '@windy/interfaces';

const config: ExternalPluginConfig = {
    name: 'windy-plugin-shipposition',
    version: '3.0.0',
    icon: '🛰️',
    title: 'Ship Position',
    description: 'Ship Position',
    author: 'Yann Kerherve (ENSM)',
    repository: 'https://github.com/YannKerherve/Ship-position',
    desktopUI: 'embedded',
    mobileUI: 'small',
    routerPath: '/my-plugin',
}; 

export default config;
