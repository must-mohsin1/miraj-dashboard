import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-24">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Miraj Dashboard</CardTitle>
          <CardDescription>Next.js frontend scaffold is ready.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input placeholder="Type something…" aria-label="Sample input" />
          <Dialog>
            <DialogTrigger asChild>
              <Button>Open dialog</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Hello</DialogTitle>
                <DialogDescription>
                  This dialog verifies Radix UI and the dialog component.
                </DialogDescription>
              </DialogHeader>
            </DialogContent>
          </Dialog>
        </CardContent>
        <CardFooter>
          <Tabs defaultValue="table" className="w-full">
            <TabsList>
              <TabsTrigger value="table">Table</TabsTrigger>
              <TabsTrigger value="empty">Empty</TabsTrigger>
            </TabsList>
            <TabsContent value="table">
              <Table>
                <TableCaption>Sample table view</TableCaption>
                <TableHeader>
                  <TableRow>
                    <TableHead>Asset</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell>BTC</TableCell>
                    <TableCell className="text-right">$100,000</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </TabsContent>
            <TabsContent value="empty">
              <p className="text-sm text-muted-foreground">Nothing here yet.</p>
            </TabsContent>
          </Tabs>
        </CardFooter>
      </Card>
    </main>
  );
}
