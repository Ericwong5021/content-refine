import config from '../../site.config.json';

export interface SiteConfig {
  id?: string;
  title?: string;
  subtitle?: string;
  author?: string;
  brandMark?: string;
  theme?: string;
  dek?: string;
  description?: string;
}

export const siteConfig: SiteConfig = config as unknown as SiteConfig;
export default siteConfig;
