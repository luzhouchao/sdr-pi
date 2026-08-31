export class RunLease {
  constructor() {
    this.owner = undefined;
  }

  acquire(owner) {
    if (this.owner !== undefined) return undefined;
    const token = Symbol(owner);
    this.owner = { name: owner, token };
    let released = false;
    return () => {
      if (released) return;
      released = true;
      if (this.owner?.token !== token) {
        throw new Error("run lease ownership mismatch");
      }
      this.owner = undefined;
    };
  }

  state() {
    return { busy: this.owner !== undefined, owner: this.owner?.name };
  }
}
