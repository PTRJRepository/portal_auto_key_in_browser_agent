import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  summarizeTemplate,
  validateTemplatePackage,
  type TemplatePackage,
  type TemplateSummary
} from "@template/flow-schema";

export class TemplateStore {
  private readonly byId = new Map<string, TemplatePackage>();

  constructor(private readonly templateDir: string) {}

  public async initialize(): Promise<void> {
    await mkdir(this.templateDir, { recursive: true });
    const files = await readdir(this.templateDir);
    for (const filename of files) {
      if (!filename.endsWith(".json")) {
        continue;
      }
      const absolutePath = path.join(this.templateDir, filename);
      try {
        const raw = await readFile(absolutePath, "utf8");
        const parsed = validateTemplatePackage(JSON.parse(raw));
        this.byId.set(parsed.template.id, parsed);
      } catch {
        // Ignore broken files so one malformed template does not break startup.
      }
    }
  }

  public list(): TemplateSummary[] {
    return Array.from(this.byId.values()).map(summarizeTemplate);
  }

  public get(templateId: string): TemplatePackage | undefined {
    return this.byId.get(templateId);
  }

  public async save(templatePackage: TemplatePackage): Promise<void> {
    this.byId.set(templatePackage.template.id, templatePackage);
    const filePath = path.join(this.templateDir, `${templatePackage.template.id}.json`);
    await writeFile(filePath, JSON.stringify(templatePackage, null, 2), "utf8");
  }
}

