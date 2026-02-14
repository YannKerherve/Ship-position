import type { ExternalPluginConfig } from '@windy/interfaces';

const config: ExternalPluginConfig = {
    name: 'windy-plugin-my-plugin',
    version: '0.1.0',
    icon: '🔌',
    title: 'Ship Position',
    description: 'Ship Position',
    author: 'Yann Kerherve (ENSM)',
    repository: 'https://github.com/windycom/windy-plugin-template',
    desktopUI: 'embedded',
    mobileUI: 'small',
    routerPath: '/my-plugin',
}; 

export default config;
